"""IFC → BuildingModel. Reads IFC2x3/IFC4 with IfcOpenShell; SI units; never guesses.

Order of preference for every value: standard attribute / property set / quantity set, then
geometry (plan outlines are the union of the element's triangles projected to the ground plane),
else null — which the engine reports as "cannot verify" and turns into a question.
`source_id` is the IFC GlobalId, used to colour elements in the web viewer and in BCF.

Site context, so a well-modelled IFC needs no questions:
  roads      IfcRoad / IfcCivilElement / IfcGeographicElement / proxy named or typed "road"…
             A plot side with a road just outside it is a road edge; the width is measured across
             the road geometry (CC_Road.Width and CC_Road.WidthBasis override). With at least one
             road modelled, the other sides are inferred to be neighbours.
  facts      Pset_BuildingCommon.OccupancyType ("A-4" → group A, subdivision A-4),
             Pset_SiteCommon.TotalArea (plot area), and CC_Planning on IfcSite or IfcBuilding:
             Zone, CongestedArea, BuildingType (the facts Revit keeps in Site Setup).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.geolocation as geo
import ifcopenshell.util.unit as uunit
from shapely.geometry import Polygon
from shapely.ops import unary_union

from compliance.adapters import mesh
from compliance.adapters.usage import guess

_GROUND = re.compile(r"\b(ground|gf|g\.f\.|level 0|level 00|00)\b", re.I)
_COMMERCIAL = re.compile(r"shop|retail|commercial|showroom", re.I)
_ROAD = re.compile(r"\b(road|street|lane|carriageway|rasta|marg)\b", re.I)
_OCCUPANCY = re.compile(r"^\s*([A-HJ])(?:\s*-\s*(\d+))?\s*$", re.I)
_BUILDING_TYPES = {"group_housing", "standalone", "bungalow_self_use", "mixed_use", "other"}
_ROAD_CLASSES = ("IfcRoad", "IfcCivilElement", "IfcGeographicElement", "IfcBuildingElementProxy")


def _f(value: Any, source: str = "model", note: str | None = None) -> dict[str, Any]:
    out = {"value": value, "source": source if value is not None else "default"}
    if note:
        out["note"] = note
    return out


class _Reader:
    def __init__(self, ifc: ifcopenshell.file, shapes: mesh.Shapes | None = None) -> None:
        self.ifc = ifc
        self.scale = uunit.calculate_unit_scale(ifc)  # project length unit → metres
        self.settings = mesh.settings()
        self.warnings: list[str] = []
        self._shapes = shapes

    def _all_shapes(self) -> mesh.Shapes:
        """One multi-threaded tessellation pass over the file (much faster than per element),
        unless the caller already ran it (an upload shares it with the viewer mesh)."""
        if self._shapes is None:
            self._shapes = mesh.tessellate(self.ifc)
        return self._shapes

    def length(self, v: Any) -> float | None:
        return None if v is None else round(float(v) * self.scale, 4)

    def props(self, el) -> dict[str, dict[str, Any]]:
        try:
            return uel.get_psets(el)
        except Exception:  # noqa: BLE001
            return {}

    def prop(self, el, pset: str, name: str) -> Any:
        return self.props(el).get(pset, {}).get(name)

    def shape(self, el):
        if not getattr(el, "Representation", None):
            return None
        cached = self._all_shapes().get(el.GlobalId)
        if cached is not None:
            verts, faces = cached
            return SimpleNamespace(geometry=SimpleNamespace(verts=verts, faces=faces))
        try:
            return ifcopenshell.geom.create_shape(self.settings, el)
        except Exception as e:  # noqa: BLE001 - bad geometry: skip the element's geometry only
            self.warnings.append(f"geometry of {el.is_a()} {el.GlobalId} unreadable: {e}")
            return None

    def plan(self, el) -> Polygon | None:
        """Outline of the element seen from above (metres)."""
        shape = self.shape(el)
        if shape is None:
            return None
        v = shape.geometry.verts
        faces = shape.geometry.faces
        tris = []
        for i in range(0, len(faces), 3):
            pts = [(v[3 * faces[i + k]], v[3 * faces[i + k] + 1]) for k in range(3)]
            p = Polygon(pts)
            if p.area > 1e-6:
                tris.append(p)
        if not tris:
            return None
        u = unary_union(tris)
        if u.geom_type == "MultiPolygon":
            u = max(u.geoms, key=lambda g: g.area)
        return Polygon(u.exterior.coords).simplify(0.005) if u.area > 0 else None

    def z_range(self, el) -> tuple[float, float] | None:
        shape = self.shape(el)
        if shape is None or not shape.geometry.verts:
            return None
        zs = shape.geometry.verts[2::3]
        return min(zs), max(zs)


def _coords(poly: Polygon | None) -> list[list[float]] | None:
    if poly is None:
        return None
    pts = list(poly.exterior.coords)[:-1]
    if Polygon(pts).exterior.is_ccw is False:
        pts.reverse()
    return [[round(x, 4), round(y, 4)] for x, y in pts]


def _area(area: Any, scale: float, poly: Polygon | None) -> float | None:
    if area is not None:
        return round(area * scale**2, 4)
    return round(poly.area, 4) if poly else None


def _stair_exit(fire_exit: Any) -> dict[str, Any]:
    if fire_exit is not None:
        return _f(bool(fire_exit), "model", "Pset_StairCommon.FireExit")
    return {
        "value": True,
        "source": "inferred",
        "confidence": 0.6,
        "note": "staircases assumed to be exit routes",
    }


def _roads(ifc: ifcopenshell.file, r: _Reader) -> list[tuple[Polygon, dict[str, Any]]]:
    out = []
    for cls in _ROAD_CLASSES:
        try:
            candidates = ifc.by_type(cls)
        except RuntimeError:  # class not in this schema (IfcRoad is IFC4x3 only)
            continue
        for el in candidates:
            label = " ".join(
                str(getattr(el, a, None) or "") for a in ("Name", "ObjectType", "LongName")
            )
            if cls != "IfcRoad" and not _ROAD.search(label):
                continue
            poly = r.plan(el)
            if poly is not None:
                out.append((poly, r.props(el).get("CC_Road", {})))
    return out


def _tag_edges(edges: list[dict[str, Any]], roads: list[tuple[Polygon, dict[str, Any]]]) -> None:
    """Road edges: a modelled road just outside the side's midpoint. Width: across the road."""
    from shapely.geometry import LineString, Point

    if not edges or not roads:
        return
    for e in edges:
        (ax, ay), (bx, by) = e["a"], e["b"]
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
        nx, ny = (by - ay) / length, -(bx - ax) / length  # outward for a CCW boundary
        mx, my = (ax + bx) / 2, (ay + by) / 2
        probe = Point(mx + nx * 0.5, my + ny * 0.5)
        hit = next(((poly, p) for poly, p in roads if poly.distance(probe) < 0.6), None)
        if hit is None:
            e["kind"] = {
                "value": "neighbour",
                "source": "inferred",
                "confidence": 0.7,
                "note": "no road modelled along this side",
            }
            continue
        poly, props = hit
        ray = LineString([(mx, my), (mx + nx * 200, my + ny * 200)]).intersection(poly)
        width = props.get("Width") or (round(ray.length, 2) if not ray.is_empty else None)
        e["kind"] = _f("road", "model", "road modelled along this side")
        e["road_width_m"] = _f(
            width, "model", "CC_Road.Width" if props.get("Width") else "measured across the road"
        )
        basis = props.get("WidthBasis")
        e["road_width_basis"] = (
            _f(basis, "model", "CC_Road.WidthBasis")
            if basis in ("existing", "development_plan")
            else {"value": "existing", "source": "inferred", "confidence": 0.6,
                  "note": "width of the modelled road"}
        )  # fmt: skip


def _rooms_at(door: Polygon | None, spaces: list[dict[str, Any]]) -> list[str]:
    """The (up to two) rooms a door sits between: room outlines within 0.3 m of the door leaf."""
    if door is None:
        return []
    c = door.centroid
    near = sorted(
        (Polygon(s["polygon"]).distance(c), s["id"])
        for s in spaces
        if s["polygon"] and Polygon(s["polygon"]).distance(c) < 0.3
    )
    return [sid for _, sid in near[:2]]


def _planning(r: _Reader, site, building) -> dict[str, dict[str, Any]]:
    """Planning facts carried as properties (see module docstring)."""
    out: dict[str, dict[str, Any]] = {}
    occ = r.prop(building, "Pset_BuildingCommon", "OccupancyType") if building else None
    m = _OCCUPANCY.match(str(occ)) if occ else None
    if m:
        group = m.group(1).upper()
        sub = f"{group}-{m.group(2)}" if m.group(2) else None
        out["occupancy"] = _f(
            {"group": group, "subdivision": sub}, "model", "Pset_BuildingCommon.OccupancyType"
        )
    plan: dict[str, Any] = {}
    for el in (site, building):
        if el is not None:
            plan.update({k: v for k, v in r.props(el).get("CC_Planning", {}).items() if v != ""})
    if isinstance(plan.get("Zone"), str):
        out["zone"] = _f(plan["Zone"], "model", "CC_Planning.Zone")
    if isinstance(plan.get("CongestedArea"), bool):
        out["congested_area"] = _f(plan["CongestedArea"], "model", "CC_Planning.CongestedArea")
    if plan.get("BuildingType") in _BUILDING_TYPES:
        out["building_type"] = _f(plan["BuildingType"], "model", "CC_Planning.BuildingType")
    total = r.prop(site, "Pset_SiteCommon", "TotalArea") if site else None
    if total:
        out["plot_area_declared_m2"] = _f(
            round(total * r.scale**2, 4), "model", "Pset_SiteCommon.TotalArea"
        )
    return out


def read(
    path: str | Path, *, ifc: ifcopenshell.file | None = None, shapes: mesh.Shapes | None = None
) -> tuple[dict[str, Any], list[str]]:
    """(BuildingModel dict, warnings). Pass the opened file and its geometry pass to reuse them."""
    ifc = ifc or ifcopenshell.open(str(path))
    r = _Reader(ifc, shapes)
    project = (ifc.by_type("IfcProject") or [None])[0]
    site = (ifc.by_type("IfcSite") or [None])[0]
    building = (ifc.by_type("IfcBuilding") or [None])[0]

    location = None
    if site is not None and site.RefLatitude and site.RefLongitude:
        location = {
            "lat": round(geo.dms2dd(*site.RefLatitude), 6),
            "lon": round(geo.dms2dd(*site.RefLongitude), 6),
        }

    # ------------------------------------------------------------------ storeys
    storeys = sorted(ifc.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0.0)
    level_id = {s.id(): (s.Name or f"Storey {i}") for i, s in enumerate(storeys)}
    ground_storey = next((s for s in storeys if _GROUND.search(s.Name or "")), None) or next(
        (s for s in storeys if r.length(s.Elevation or 0) >= -0.01), storeys[0] if storeys else None
    )
    ground = r.length(ground_storey.Elevation or 0.0) if ground_storey else None
    levels = [
        {
            "id": level_id[s.id()],
            "source_id": s.GlobalId,
            "name": s.Name or level_id[s.id()],
            "elevation_m": r.length(s.Elevation or 0.0),
            "is_basement": ground is not None and r.length(s.Elevation or 0.0) < ground - 0.01,
        }
        for s in storeys
    ]

    def storey_of(el) -> str | None:
        c = uel.get_container(el) or (uel.get_aggregate(el) if el.is_a("IfcSpace") else None)
        while c is not None and not c.is_a("IfcBuildingStorey"):
            c = uel.get_aggregate(c)
        return level_id.get(c.id()) if c is not None else None

    # ------------------------------------------------------------------ site boundary
    boundary = None
    if site is not None and site.Representation:
        for rep in site.Representation.Representations:
            if rep.RepresentationIdentifier == "FootPrint":
                for item in rep.Items:
                    pts = getattr(item, "Points", None)
                    if pts is not None and hasattr(pts, "__iter__"):
                        coords = [
                            (p.Coordinates[0] * r.scale, p.Coordinates[1] * r.scale) for p in pts
                        ]
                    elif hasattr(item, "Points") and hasattr(item.Points, "CoordList"):
                        coords = [(x * r.scale, y * r.scale) for x, y, *_ in item.Points.CoordList]
                    else:
                        continue
                    if len(coords) > 3 and coords[0] == coords[-1]:
                        coords = coords[:-1]
                    if len(coords) >= 3:
                        boundary = _coords(Polygon(coords))
    if boundary is None:
        r.warnings.append("No site footprint (property lines): margins and FSI can't be checked.")
    edges = []
    if boundary:
        for i, a in enumerate(boundary):
            b = boundary[(i + 1) % len(boundary)]
            edges.append({
                "id": f"e{i + 1}", "a": a, "b": b,
                "kind": _f(None), "road_width_m": _f(None), "road_width_basis": _f(None),
            })  # fmt: skip
    _tag_edges(edges, _roads(ifc, r))
    road_edges = sum(1 for e in edges if e["kind"]["value"] == "road")
    planning = _planning(r, site, building)

    # ------------------------------------------------------------------ spaces
    spaces = []
    for sp in ifc.by_type("IfcSpace"):
        if getattr(sp, "PredefinedType", None) in ("GFA", "EXTERNAL"):
            continue
        qto = r.props(sp).get("Qto_SpaceBaseQuantities", {})
        poly = r.plan(sp)
        area = qto.get("NetFloorArea") or qto.get("GrossFloorArea")
        height = qto.get("FinishCeilingHeight") or qto.get("Height")
        if height is None and (z := r.z_range(sp)):
            height = (z[1] - z[0]) / r.scale
        name = sp.LongName or sp.Name or sp.GlobalId
        spaces.append({
            "id": sp.Name or sp.GlobalId,
            "source_id": sp.GlobalId,
            "name": name,
            "level_id": storey_of(sp) or (levels[0]["id"] if levels else ""),
            "usage": guess(name),
            "area_m2": _area(area, r.scale, poly),
            "clear_height_m": r.length(height),
            "polygon": _coords(poly),
        })  # fmt: skip

    # ------------------------------------------------------------------ FSI areas: storey GFA
    areas = []
    for s in storeys:
        gfa = r.props(s).get("Qto_BuildingStoreyBaseQuantities", {}).get("GrossFloorArea")
        if gfa is not None:
            areas.append({
                "id": f"GFA-{level_id[s.id()]}",
                "source_id": s.GlobalId,
                "scheme": "IFC storey gross floor area",
                "level_id": level_id[s.id()],
                "name": f"Gross floor area {s.Name or ''}".strip(),
                "area_m2": round(gfa * r.scale**2, 4),
                "counts_to_far": _f(True, note="storey GrossFloorArea quantity"),
            })  # fmt: skip
    if not areas:
        r.warnings.append("No storey GrossFloorArea quantities: FSI can't be calculated.")

    # ------------------------------------------------------------------ footprint & heights
    slabs = [
        el
        for el in ifc.by_type("IfcSlab")
        if storey_of(el) == (level_id.get(ground_storey.id()) if ground_storey else None)
    ]
    floor_slabs = [
        el for el in slabs if getattr(el, "PredefinedType", None) in ("FLOOR", "BASESLAB", None)
    ]
    plans = [p for p in (r.plan(el) for el in floor_slabs) if p is not None]
    footprint = max(plans, key=lambda p: p.area) if plans else None
    if footprint is None:
        ground_spaces = [
            Polygon(s["polygon"])
            for s in spaces
            if s["polygon"] and s["level_id"] == (levels[0]["id"] if levels else None)
        ]
        if ground_spaces:
            u = unary_union(ground_spaces)
            footprint = Polygon(u.convex_hull.exterior.coords) if u.area > 0 else None
    roofs = [el for el in ifc.by_type("IfcRoof")] + [
        el for el in ifc.by_type("IfcSlab") if getattr(el, "PredefinedType", None) == "ROOF"
    ]
    roof_top = max((z[1] for el in roofs if (z := r.z_range(el))), default=None)
    highest = max(
        (z[1] for el in ifc.by_type("IfcElement") if storey_of(el) and (z := r.z_range(el))),
        default=roof_top,
    )  # building elements only: roads and neighbouring context sit on the site
    if roof_top is None:
        # No roof element: the top of the building's own elements, not the top floor's level
        # (which would leave out the whole top storey).
        roof_top = (
            highest if highest is not None else (levels[-1]["elevation_m"] if storeys else None)
        )
        if roof_top is not None:
            r.warnings.append(
                "No roof in the model: the building height is taken from its highest element."
            )

    # ------------------------------------------------------------------ stairs
    stairs = []
    for st in ifc.by_type("IfcStair"):
        flights = [el for el in (uel.get_decomposition(st) or []) if el.is_a("IfcStairFlight")] or [
            st
        ]
        widths, risers, treads = [], [], []
        for fl in flights:
            p = r.props(fl).get("Pset_StairFlightCommon", {})
            if p.get("RiserHeight") is not None:
                risers.append(p["RiserHeight"])
            if p.get("TreadLength") is not None:
                treads.append(p["TreadLength"])
            if (poly := r.plan(fl)) is not None:
                rect = list(poly.minimum_rotated_rectangle.exterior.coords)
                sides = [
                    ((rect[i][0] - rect[i + 1][0]) ** 2 + (rect[i][1] - rect[i + 1][1]) ** 2) ** 0.5
                    for i in range(4)
                ]
                widths.append(min(sides))
        fire_exit = r.prop(st, "Pset_StairCommon", "FireExit")
        stairs.append({
            "id": st.Name or st.GlobalId,
            "source_id": st.GlobalId,
            "base_level_id": storey_of(st) or (levels[0]["id"] if levels else ""),
            "top_level_id": None,
            "min_run_width_m": round(min(widths), 4) if widths else None,
            "riser_m": r.length(max(risers)) if risers else None,
            "tread_m": r.length(min(treads)) if treads else None,
            "is_exit": _stair_exit(fire_exit),
        })  # fmt: skip

    # ------------------------------------------------------------------ doors
    doors = []
    for d in ifc.by_type("IfcDoor"):
        external = r.prop(d, "Pset_DoorCommon", "IsExternal")
        fire_exit = r.prop(d, "Pset_DoorCommon", "FireExit")
        if fire_exit is not None:
            is_exit = _f(bool(fire_exit), "model", "Pset_DoorCommon.FireExit")
        elif external is not None:
            is_exit = {
                "value": bool(external),
                "source": "inferred",
                "confidence": 0.7,
                "note": "Pset_DoorCommon.IsExternal",
            }
        else:
            is_exit = _f(None, note="is this an exit door?")
        level = storey_of(d) or (levels[0]["id"] if levels else "")
        joins = _rooms_at(r.plan(d), [s for s in spaces if s["level_id"] == level])
        doors.append({
            "id": d.Name or d.GlobalId,
            "source_id": d.GlobalId,
            "level_id": level,
            "width_m": r.length(d.OverallWidth),
            "height_m": r.length(d.OverallHeight),
            "is_exit": is_exit,
            "from_space_id": joins[0] if joins else None,
            "to_space_id": joins[1] if len(joins) > 1 else None,
        })  # fmt: skip

    # ------------------------------------------------------------------ tenements (zones)
    names_to_level = {lv["name"]: lv["id"] for lv in levels}
    units = []
    for z in ifc.by_type("IfcZone"):
        p = r.props(z).get("CC_Unit", {})
        members = [
            m for rel in (z.IsGroupedBy or []) for m in rel.RelatedObjects if m.is_a("IfcSpace")
        ]
        carpet = p.get("CarpetArea")
        if carpet is None and members:
            vals = [
                r.props(m).get("Qto_SpaceBaseQuantities", {}).get("NetFloorArea") for m in members
            ]
            carpet = sum(vals) if all(v is not None for v in vals) else None
        use = p.get("Use") or ("commercial" if _COMMERCIAL.search(z.Name or "") else "residential")
        level = names_to_level.get(p.get("Level")) or (storey_of(members[0]) if members else None)
        units.append({
            "id": z.Name or z.GlobalId,
            "source_id": z.GlobalId,
            "name": z.Name or z.GlobalId,
            "level_id": level or (levels[0]["id"] if levels else ""),
            "carpet_area_m2": round(carpet * r.scale**2, 4) if carpet is not None else None,
            "use": (
                {"value": use, "source": "model"}
                if p.get("Use")
                else {"value": use, "source": "inferred", "confidence": 0.6}
            ),
        })  # fmt: skip

    def default(v=None):
        return _f(v)

    model = {
        "schema_version": "1.0",
        "meta": {
            "source_kind": "ifc",
            "source_file": Path(path).name,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool_version": f"ifcopenshell {ifcopenshell.version}",
        },
        "project": {
            "name": (project.Name if project and project.Name else Path(path).stem),
            "location": _f(location, "model", "IfcSite RefLatitude / RefLongitude")
            if location
            else default(),
            "authority_id": _f(None, note="resolved by the server from the location"),
            "rulesets": _f(None, note="resolved by the server from the location"),
            "occupancy": planning.get("occupancy", default()),
            "zone": planning.get("zone", default()),
            "congested_area": planning.get("congested_area", default()),
            "special": {
                k: default()
                for k in (
                    "heritage",
                    "coastal",
                    "airport_zone",
                    "ht_line",
                    "railway",
                    "river_flood_line",
                    "hill_slope_bdp",
                    "defence_vicinity",
                    "metro_rail_within_20m",
                )
            },  # fmt: skip
            "building_type": planning.get("building_type", default()),
            "overlays": {
                "nearest_metro_station": default(),
                "metro_tod": default(),
                "plot_share_in_tod": default(),
            },
        },
        "site": {
            "boundary": boundary,
            "plot_area_declared_m2": planning.get("plot_area_declared_m2", default()),
            "is_corner_plot": (
                {
                    "value": road_edges >= 2,
                    "source": "inferred",
                    "confidence": 0.7,
                    "note": "roads modelled on two or more sides",
                }
                if road_edges
                else default()
            ),  # fmt: skip
            "ground_level_m": ground,
            "edges": edges,
        },
        "levels": levels,
        "building": {
            "footprint": _coords(footprint),
            "roof_top_m": round(roof_top, 4) if roof_top is not None else None,
            "highest_point_m": round(highest, 4) if highest is not None else None,
        },
        "spaces": spaces,
        "areas": areas,
        "stairs": stairs,
        "doors": doors,
        "units": units,
    }
    if r.warnings:
        model["_notes"] = list(dict.fromkeys(r.warnings))
    return model, r.warnings


def north_deg(path: str | Path, ifc: Any = None) -> float | None:
    """The model's true north as the site setup's rotation (degrees, anticlockwise: how far the
    model's +y is turned from north towards west), from the model context's TrueNorth. None when
    the file doesn't say."""
    ifc = ifc or ifcopenshell.open(str(path))
    for ctx in ifc.by_type("IfcGeometricRepresentationContext"):
        if ctx.is_a("IfcGeometricRepresentationSubContext") or ctx.ContextType not in (
            None,
            "Model",
        ):
            continue
        tn = getattr(ctx, "TrueNorth", None)
        if tn is None:
            continue
        x, y = (list(tn.DirectionRatios) + [0.0, 0.0])[:2]
        if abs(x) + abs(y) < 1e-9:
            continue
        return _angle(x, y)
    return None


def _angle(nx: float, ny: float) -> float:
    """North (nx, ny) in model axes → rotation: the model vector R(-t)·(0, 1) = (sin t, cos t)."""
    import math

    t = math.degrees(math.atan2(nx, ny))
    return round(((t + 180) % 360) - 180, 2)
