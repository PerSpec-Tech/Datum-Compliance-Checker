"""Generate sample IFC4 files from the fixture buildings (P6.1 / P8.1).

Usage: just make-samples

Writes fixtures/ifc/<name>.ifc and copies them to web/public/samples/ for the "Try a sample" button.
Generating them ourselves keeps the samples licence-clean and makes the IFC adapter testable:
reading
a sample back must give the same compliance results as the fixture it came from.

Encoding (what the adapter reads back):
  IfcSite            RefLatitude/RefLongitude; FootPrint curve = plot boundary (property lines)
  IfcBuildingStorey  Elevation; Qto_BuildingStoreyBaseQuantities.GrossFloorArea = FSI built-up area
  IfcSpace           Name = id, LongName = room name, extruded solid; Qto_SpaceBaseQuantities
                     NetFloorArea + FinishCeilingHeight (clear height)
  IfcDoor            OverallWidth / OverallHeight; Pset_DoorCommon.IsExternal (exit door)
  IfcStairFlight     box geometry (short side = run width);
                     Pset_StairFlightCommon RiserHeight / TreadLength
  IfcSlab FLOOR/ROOF building footprint at ground; roof top
  IfcZone            one per tenement; CC_Unit.CarpetArea / Level / Use (carpet area isn't standard)
  IfcSite            Body = plot ground; Pset_SiteCommon.TotalArea; CC_Planning Zone /
                     CongestedArea / BuildingType
  IfcBuilding        Pset_BuildingCommon.OccupancyType (e.g. A-4)
  IfcCivilElement    one road strip per road side, as wide as the road (CC_Road.WidthBasis)
  IfcBuildingElementProxy  neighbouring buildings (context only, contained in the site)
"""

import json
import math
import shutil
import subprocess
import sys

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.group
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.util.geolocation
import numpy as np
from ifcopenshell.util.shape_builder import ShapeBuilder
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

from compliance.config import REPO_ROOT

NAMES = ["compliant_house", "violating_apartment", "demo_apartment", "demo_house"]
WEB_SAMPLES = {"demo_apartment", "demo_house"}  # what the web app offers under "Try a sample"
OUT = REPO_ROOT / "fixtures" / "ifc"
WEB = REPO_ROOT / "web" / "public" / "samples"


def placement(f, product, x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    ifcopenshell.api.geometry.edit_object_placement(f, product=product, matrix=m, is_si=True)


def extruded(f, body, builder, product, polygon, height):
    curve = builder.polyline([tuple(p) for p in polygon], closed=True)
    solid = builder.extrude(builder.profile(curve), magnitude=height)
    rep = builder.get_representation(body, [solid])
    ifcopenshell.api.geometry.assign_representation(f, product=product, representation=rep)


def box(f, body, builder, product, x, y, sx, sy, height):
    extruded(
        f, body, builder, product, [(x, y), (x + sx, y), (x + sx, y + sy), (x, y + sy)], height
    )


def strip(a, b, width, offset=0.0, extend=0.0):
    """Rectangle on the outer side of plot edge a→b (CCW boundary), `offset` metres away."""
    (ax, ay), (bx, by) = a, b
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    ux, uy = (bx - ax) / length, (by - ay) / length
    nx, ny = uy, -ux
    a0 = (ax - ux * extend + nx * offset, ay - uy * extend + ny * offset)
    b0 = (bx + ux * extend + nx * offset, by + uy * extend + ny * offset)
    return [a0, b0, (b0[0] + nx * width, b0[1] + ny * width), (a0[0] + nx * width, a0[1] + ny * width)]


# ---------------------------------------------------------------------------- walls, doors, windows
EXT_T, INT_T = 0.23, 0.115  # wall thickness (m), centred on the room outlines
WINDOW_USES = {"living", "bedroom", "habitable", "kitchen", "retail", "office"}


def solid(builder, polygon, z0, height):
    curve = builder.polyline([tuple(p) for p in polygon], closed=True)
    return builder.extrude(builder.profile(curve), magnitude=height, position=(0.0, 0.0, z0))


def assign(f, body, builder, product, items):
    rep = builder.get_representation(body, items)
    ifcopenshell.api.geometry.assign_representation(f, product=product, representation=rep)


def band(p, q, thickness, extend=0.0):
    """Rectangle of `thickness` centred on segment p→q, optionally extended at both ends."""
    (px, py), (qx, qy) = p, q
    length = ((qx - px) ** 2 + (qy - py) ** 2) ** 0.5
    ux, uy = (qx - px) / length, (qy - py) / length
    nx, ny = -uy * thickness / 2, ux * thickness / 2
    px, py, qx, qy = px - ux * extend, py - uy * extend, qx + ux * extend, qy + uy * extend
    return [(px + nx, py + ny), (qx + nx, qy + ny), (qx - nx, qy - ny), (px - nx, py - ny)]


def straight_runs(line):
    """Split a merged polyline into straight pieces (walls are straight)."""
    pts = list(line.coords)
    runs, start = [], pts[0]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-9:
            runs.append((start, b))
            start = b
    runs.append((start, pts[-1]))
    return runs


def wall_pieces(spaces, footprint):
    fp = Polygon(footprint)
    lines = [LineString(list(fp.exterior.coords))]
    lines += [LineString(list(Polygon(s["polygon"]).exterior.coords)) for s in spaces]
    merged = linemerge(unary_union(lines))
    geoms = merged.geoms if hasattr(merged, "geoms") else [merged]
    pieces = []
    for g in geoms:
        for a, b in straight_runs(g):
            seg = LineString([a, b])
            if seg.length < 0.05:
                continue
            mid = seg.interpolate(0.5, normalized=True)
            exterior = fp.exterior.distance(mid) < 1e-6
            if exterior:  # open stilt parking has no outer wall
                (ax, ay), (bx, by) = a, b
                ln = seg.length
                inward = Point(mid.x - (by - ay) / ln * 0.05, mid.y + (bx - ax) / ln * 0.05)
                if not fp.contains(inward):
                    inward = Point(mid.x + (by - ay) / ln * 0.05, mid.y - (bx - ax) / ln * 0.05)
                inside = next((sp for sp in spaces if Polygon(sp["polygon"]).contains(inward)), None)
                if inside and inside["usage"]["value"] == "parking":
                    continue
            pieces.append({"a": a, "b": b, "line": seg, "exterior": exterior})
    return pieces


def opening_in(f, body, builder, wall_piece, center, direction, width, z0, height, thickness):
    c, (ux, uy) = center, direction
    p = (c.x - ux * width / 2, c.y - uy * width / 2)
    q = (c.x + ux * width / 2, c.y + uy * width / 2)
    opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement")
    placement(f, opening)
    assign(f, body, builder, opening, [solid(builder, band(p, q, thickness + 0.1), z0, height)])
    ifcopenshell.api.feature.add_feature(f, feature=opening, element=wall_piece["entity"])
    return opening, p, q


def longest_part(geom):
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "LineString"]
    if not parts:
        return None
    merged = linemerge(unary_union(parts)) if len(parts) > 1 else parts[0]
    parts = list(getattr(merged, "geoms", [merged]))
    return max(parts, key=lambda g: g.length)


def door_line(d, polys, fp):
    a = polys.get(d["from_space_id"])
    if a is None:
        return None
    if d["to_space_id"]:
        b = polys.get(d["to_space_id"])
        return longest_part(a.boundary.intersection(b.boundary)) if b is not None else None
    ext = a.boundary.intersection(fp.exterior)
    parts = [g for g in getattr(ext, "geoms", [ext]) if g.geom_type == "LineString"]
    if not parts:
        return None
    # The entrance faces the road (plot edge e1 runs along y = 0 in every fixture).
    return min(parts, key=lambda g: (round(g.centroid.y, 3), -g.length))


def direction(line):
    (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
    ln = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    return (bx - ax) / ln, (by - ay) / ln


def envelope(f, body, builder, m, storeys, levels):
    """Walls along every room outline and the footprint, doors in the walls between the rooms
    they connect, and windows on the outer walls of habitable rooms, kitchens and shops."""
    fp = Polygon(m["building"]["footprint"])
    tops = {lv["id"]: nxt["elevation_m"] - 0.2 for lv, nxt in zip(levels, levels[1:])}
    tops[levels[-1]["id"]] = m["building"]["roof_top_m"] - 0.2
    placed = 0
    for lv in levels:
        spaces = [sp for sp in m["spaces"] if sp["level_id"] == lv["id"] and sp["polygon"]]
        if not spaces:
            continue
        z0, st = lv["elevation_m"], storeys[lv["id"]]
        height = tops[lv["id"]] - z0
        pieces = wall_pieces(spaces, m["building"]["footprint"])
        for i, wp in enumerate(pieces):
            t = EXT_T if wp["exterior"] else INT_T
            wall = ifcopenshell.api.root.create_entity(
                f, ifc_class="IfcWall", predefined_type="SOLIDWALL" if wp["exterior"] else "PARTITIONING",
                name=f"{lv['id']}-W{i + 1}",
            )
            ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=st)
            placement(f, wall)
            assign(f, body, builder, wall, [solid(builder, band(wp["a"], wp["b"], t, t / 2), z0, height)])
            ps = ifcopenshell.api.pset.add_pset(f, product=wall, name="Pset_WallCommon")
            ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"IsExternal": wp["exterior"]})
            wp["entity"], wp["t"] = wall, t

        def host(center):
            return next((wp for wp in pieces if wp["line"].distance(center) < 1e-6), None)

        polys = {sp["id"]: Polygon(sp["polygon"]) for sp in spaces}
        taken: dict[int, list[tuple[float, float]]] = {}  # wall piece → occupied stretches
        for d in [d for d in m["doors"] if d["level_id"] == lv["id"]]:
            line = door_line(d, polys, fp)
            center = line.interpolate(0.5, normalized=True) if line is not None else None
            wp = host(center) if center is not None else None
            if wp is None:
                continue
            u = direction(wp["line"])
            opening, p, q = opening_in(f, body, builder, wp, center, u, d["width_m"], z0, d["height_m"], wp["t"])
            door = make_door(f, d, st)
            placement(f, door)
            assign(f, body, builder, door, [solid(builder, band(p, q, 0.05), z0, d["height_m"])])
            ifcopenshell.api.feature.add_filling(f, opening=opening, element=door)
            s0 = wp["line"].project(Point(p))
            s1 = wp["line"].project(Point(q))
            taken.setdefault(id(wp), []).append((min(s0, s1) - 0.3, max(s0, s1) + 0.3))
            d["_placed"] = True
            placed += 1

        for sp in spaces:
            if sp["usage"]["value"] not in WINDOW_USES:
                continue
            retail = sp["usage"]["value"] == "retail"
            best = None  # (free length, piece, s_from, s_to)
            for wp in pieces:
                if not wp["exterior"] or polys[sp["id"]].boundary.distance(wp["line"].interpolate(0.5, normalized=True)) > 1e-6:
                    continue
                cuts = sorted(taken.get(id(wp), []))
                cursor = 0.0
                for s0, s1 in cuts + [(wp["line"].length, wp["line"].length)]:
                    if s0 - cursor > (best[0] if best else 0):
                        best = (s0 - cursor, wp, cursor, s0)
                    cursor = max(cursor, s1)
            if best is None or best[0] < 1.2:
                continue
            free, wp, s_from, s_to = best
            width = min(free - 0.6, 3.0 if retail else 1.8)
            sill, wh = (0.6, 2.0) if retail else (0.9, 1.2)
            if width < 0.6 or sill + wh > height - 0.1:
                continue
            center = wp["line"].interpolate((s_from + s_to) / 2)
            opening, p, q = opening_in(f, body, builder, wp, center, direction(wp["line"]), width, z0 + sill, wh, wp["t"])
            win = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWindow", name=f"{sp['id']}-WIN")
            win.OverallWidth, win.OverallHeight = round(width, 3), wh
            ifcopenshell.api.spatial.assign_container(f, products=[win], relating_structure=st)
            placement(f, win)
            assign(f, body, builder, win, [solid(builder, band(p, q, 0.06), z0 + sill, wh)])
            ifcopenshell.api.feature.add_filling(f, opening=opening, element=win)
            taken.setdefault(id(wp), []).append((s_from, s_to))
    return placed


def make_door(f, d, st):
    door = ifcopenshell.api.root.create_entity(f, ifc_class="IfcDoor", name=d["id"])
    door.OverallWidth, door.OverallHeight = d["width_m"], d["height_m"]
    ifcopenshell.api.spatial.assign_container(f, products=[door], relating_structure=st)
    ps = ifcopenshell.api.pset.add_pset(f, product=door, name="Pset_DoorCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"IsExternal": bool(d["is_exit"]["value"])})
    return door


def dogleg_stair(f, body, builder, s, stair, storeys, levels, m):
    """Two flights per storey with a half landing, inside each level's staircase room."""
    order = [lv["id"] for lv in levels]
    lo, hi = order.index(s["base_level_id"]), order.index(s["top_level_id"] or s["base_level_id"])
    w, t = s["min_run_width_m"], s["tread_m"]
    built = 0
    for i in range(lo, hi):
        lv, nxt = levels[i], levels[i + 1]
        room = next(
            (sp for sp in m["spaces"] if sp["level_id"] == lv["id"] and sp["usage"]["value"] == "stair"),
            None,
        )
        if room is None:
            continue
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        along_y = (y1 - y0) >= (x1 - x0)

        def pt(a, b):  # a across the run, b along it
            return (a, b) if along_y else (b, a)

        a0, a1, b0 = (x0, x1, y0) if along_y else (y0, y1, x0)
        rise = nxt["elevation_m"] - lv["elevation_m"]
        n = math.ceil(rise / s["riser_m"] - 1e-9)
        r = rise / n
        n1 = math.ceil(n / 2)
        z = lv["elevation_m"]
        start = b0 + 0.3
        land = start + n1 * t
        runs = [
            [(a0 + 0.05, a0 + 0.05 + w, start + k * t, start + (k + 1) * t, z, (k + 1) * r) for k in range(n1)],
            [(a1 - 0.05 - w, a1 - 0.05, land - (k + 1) * t, land - k * t, z, (n1 + k + 1) * r) for k in range(n - n1)],
        ]
        for j, steps in enumerate(runs):
            flight = ifcopenshell.api.root.create_entity(
                f, ifc_class="IfcStairFlight", name=f"{s['id']} {lv['id']} flight {j + 1}"
            )
            ifcopenshell.api.aggregate.assign_object(f, products=[flight], relating_object=stair)
            placement(f, flight)
            items = [
                solid(builder, [pt(p, q) for p, q in ((ca, cb), (cb_, cb), (cb_, db), (ca, db))], zz, hh)
                for ca, cb_, cb, db, zz, hh in steps
            ]
            assign(f, body, builder, flight, items)
            ps = ifcopenshell.api.pset.add_pset(f, product=flight, name="Pset_StairFlightCommon")
            ifcopenshell.api.pset.edit_pset(
                f, pset=ps, properties={"RiserHeight": round(r, 4), "TreadLength": t,
                                         "NumberOfRiser": len(steps)}
            )
        landing = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcSlab", predefined_type="LANDING", name=f"{s['id']} {lv['id']} landing"
        )
        ifcopenshell.api.spatial.assign_container(f, products=[landing], relating_structure=storeys[lv["id"]])
        placement(f, landing)
        corners = [pt(a0 + 0.05, land), pt(a1 - 0.05, land), pt(a1 - 0.05, land + 1.2), pt(a0 + 0.05, land + 1.2)]
        assign(f, body, builder, landing, [solid(builder, corners, z + n1 * r - 0.15, 0.15)])
        built += 1
    return built


def build(name: str) -> None:
    m = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
    f = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcProject", name=m["project"]["name"]
    )
    length = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.unit.add_si_unit(f, unit_type="AREAUNIT")
    volume = ifcopenshell.api.unit.add_si_unit(f, unit_type="VOLUMEUNIT")
    ifcopenshell.api.unit.assign_unit(f, units=[length, area, volume])
    model_ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )
    plan_ctx = ifcopenshell.api.context.add_context(f, context_type="Plan")
    footprint_ctx = ifcopenshell.api.context.add_context(
        f,
        context_type="Plan",
        context_identifier="FootPrint",
        target_view="PLAN_VIEW",
        parent=plan_ctx,
    )
    builder = ShapeBuilder(f)

    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    loc = m["project"]["location"]["value"]
    site.RefLatitude = ifcopenshell.util.geolocation.dd2dms(loc["lat"], use_us=True)
    site.RefLongitude = ifcopenshell.util.geolocation.dd2dms(loc["lon"], use_us=True)
    site.RefElevation = 0.0
    if m["site"]["boundary"]:
        curve = builder.polyline([tuple(p) for p in m["site"]["boundary"]], closed=True)
        rep = builder.get_representation(footprint_ctx, [curve], representation_type="Curve2D")
        ifcopenshell.api.geometry.assign_representation(f, product=site, representation=rep)
    building = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuilding", name=m["project"]["name"]
    )
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)

    # Planning facts the model can carry, so the sample needs no questions.
    p = m["project"]
    occ = p["occupancy"]["value"]
    ps = ifcopenshell.api.pset.add_pset(f, product=building, name="Pset_BuildingCommon")
    ifcopenshell.api.pset.edit_pset(
        f, pset=ps, properties={"OccupancyType": occ["subdivision"] or occ["group"]}
    )
    ps = ifcopenshell.api.pset.add_pset(f, product=site, name="CC_Planning")
    ifcopenshell.api.pset.edit_pset(
        f,
        pset=ps,
        properties={
            "Zone": p["zone"]["value"],
            "CongestedArea": p["congested_area"]["value"],
            "BuildingType": p["building_type"]["value"],
        },
    )
    ps = ifcopenshell.api.pset.add_pset(f, product=site, name="Pset_SiteCommon")
    ifcopenshell.api.pset.edit_pset(
        f, pset=ps, properties={"TotalArea": m["site"]["plot_area_declared_m2"]["value"]}
    )

    # Site context: plot ground, roads and neighbouring buildings.
    if m["site"]["boundary"]:
        placement(f, site, z=-0.1)
        extruded(f, body, builder, site, m["site"]["boundary"], 0.1)
    for e in m["site"]["edges"]:
        if e["kind"]["value"] == "road":
            road = ifcopenshell.api.root.create_entity(
                f, ifc_class="IfcCivilElement", name=f"Road along {e['id']}"
            )
            road.ObjectType = "Road"
            ifcopenshell.api.spatial.assign_container(f, products=[road], relating_structure=site)
            placement(f, road, z=-0.15)
            extruded(f, body, builder, road, strip(e["a"], e["b"], e["road_width_m"]["value"], extend=12), 0.1)
            ps = ifcopenshell.api.pset.add_pset(f, product=road, name="CC_Road")
            ifcopenshell.api.pset.edit_pset(
                f, pset=ps, properties={"WidthBasis": e["road_width_basis"]["value"] or "existing"}
            )
        elif e["kind"]["value"] == "neighbour":
            nb = ifcopenshell.api.root.create_entity(
                f, ifc_class="IfcBuildingElementProxy", name=f"Neighbouring building ({e['id']})"
            )
            nb.ObjectType = "Context"
            ifcopenshell.api.spatial.assign_container(f, products=[nb], relating_structure=site)
            placement(f, nb)
            extruded(f, body, builder, nb, strip(e["a"], e["b"], 8.0, offset=1.5, extend=-2.0), 9.0)

    storeys = {}
    levels = sorted(m["levels"], key=lambda lv: lv["elevation_m"])
    for lv in levels:
        st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=lv["name"])
        st.Elevation = lv["elevation_m"]
        placement(f, st, z=lv["elevation_m"])
        ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=building)
        gfa = sum(
            a["area_m2"]
            for a in m["areas"]
            if a["level_id"] == lv["id"] and a["counts_to_far"]["value"]
        )
        if gfa:
            q = ifcopenshell.api.pset.add_qto(
                f, product=st, name="Qto_BuildingStoreyBaseQuantities"
            )
            ifcopenshell.api.pset.edit_qto(f, qto=q, properties={"GrossFloorArea": gfa})
        storeys[lv["id"]] = st

    for sp in m["spaces"]:
        space = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace", name=sp["id"])
        space.LongName = sp["name"]
        st = storeys[sp["level_id"]]
        ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=st)
        placement(f, space, z=st.Elevation)
        extruded(f, body, builder, space, sp["polygon"], sp["clear_height_m"])
        q = ifcopenshell.api.pset.add_qto(f, product=space, name="Qto_SpaceBaseQuantities")
        ifcopenshell.api.pset.edit_qto(
            f,
            qto=q,
            properties={"NetFloorArea": sp["area_m2"], "FinishCeilingHeight": sp["clear_height_m"]},
        )

    fp = m["building"]["footprint"]
    ground = next(lv for lv in levels if not lv["is_basement"])
    slab = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcSlab", predefined_type="FLOOR", name="Ground slab"
    )
    ifcopenshell.api.spatial.assign_container(
        f, products=[slab], relating_structure=storeys[ground["id"]]
    )
    placement(f, slab, z=ground["elevation_m"] - 0.2)
    extruded(f, body, builder, slab, fp, 0.2)
    for lv in levels:  # upper floor slabs, so the 3D view reads as a building
        if lv["is_basement"] or lv["id"] == ground["id"] or lv["elevation_m"] >= m["building"]["roof_top_m"] - 0.3:
            continue
        fl = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcSlab", predefined_type="FLOOR", name=f"{lv['name']} slab"
        )
        ifcopenshell.api.spatial.assign_container(f, products=[fl], relating_structure=storeys[lv["id"]])
        placement(f, fl, z=lv["elevation_m"] - 0.2)
        extruded(f, body, builder, fl, fp, 0.2)
    top = levels[-1]
    roof = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcSlab", predefined_type="ROOF", name="Roof slab"
    )
    ifcopenshell.api.spatial.assign_container(
        f, products=[roof], relating_structure=storeys[top["id"]]
    )
    placement(f, roof, z=m["building"]["roof_top_m"] - 0.2)
    extruded(f, body, builder, roof, fp, 0.2)

    envelope(f, body, builder, m, storeys, levels)
    x0, y0 = fp[0]
    for i, d in enumerate(d for d in m["doors"] if not d.pop("_placed", False)):
        # Doors the envelope couldn't place (fixtures without from/to rooms): a row by the front.
        st = storeys[d["level_id"]]
        door = make_door(f, d, st)
        placement(f, door, x=x0 + 0.5 + 1.5 * i, y=y0 - 0.1, z=st.Elevation)
        box(f, body, builder, door, 0, 0, d["width_m"], 0.2, d["height_m"])

    for s in m["stairs"]:
        st = storeys[s["base_level_id"]]
        stair = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStair", name=s["id"])
        ifcopenshell.api.spatial.assign_container(f, products=[stair], relating_structure=st)
        if not dogleg_stair(f, body, builder, s, stair, storeys, levels, m):
            flight = ifcopenshell.api.root.create_entity(
                f, ifc_class="IfcStairFlight", name=f"{s['id']} flight"
            )
            ifcopenshell.api.aggregate.assign_object(f, products=[flight], relating_object=stair)
            placement(f, flight, x=x0 + 1.0, y=y0 + 1.0, z=st.Elevation)
            box(f, body, builder, flight, 0, 0, s["min_run_width_m"], 3.0, 3.0)
            ps = ifcopenshell.api.pset.add_pset(f, product=flight, name="Pset_StairFlightCommon")
            ifcopenshell.api.pset.edit_pset(
                f, pset=ps, properties={"RiserHeight": s["riser_m"], "TreadLength": s["tread_m"]}
            )
        ps2 = ifcopenshell.api.pset.add_pset(f, product=stair, name="Pset_StairCommon")
        ifcopenshell.api.pset.edit_pset(
            f, pset=ps2, properties={"FireExit": bool(s["is_exit"]["value"])}
        )

    level_names = {lv["id"]: lv["name"] for lv in levels}
    for u in m["units"]:
        zone = ifcopenshell.api.root.create_entity(f, ifc_class="IfcZone", name=u["name"])
        zone.ObjectType = "Tenement"
        ps = ifcopenshell.api.pset.add_pset(f, product=zone, name="CC_Unit")
        ifcopenshell.api.pset.edit_pset(
            f,
            pset=ps,
            properties={
                "CarpetArea": u["carpet_area_m2"],
                "Level": level_names[u["level_id"]],
                "Use": u["use"]["value"],
            },
        )

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.ifc"
    f.write(str(path))
    if name in WEB_SAMPLES:
        WEB.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, WEB / path.name)
    print(f"wrote {path.relative_to(REPO_ROOT).as_posix()} ({path.stat().st_size // 1024} KB)")


def main() -> int:
    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "make_demo_models.py")], check=True)
    for stale in WEB.glob("*.ifc"):
        if stale.stem not in WEB_SAMPLES:
            stale.unlink()
    for name in NAMES:
        build(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
