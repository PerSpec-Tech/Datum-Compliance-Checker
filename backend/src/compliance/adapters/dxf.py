"""2D DXF → BuildingModel (P10.2). Reads drawings in the PreDCR layer standard that AutoDCR uses.

Layer roles come from rules/cities/pmc/data/predcr_layers.yaml (copied from the official manual);
`roles` can override or extend them (the web app's layer table, P10.3/P10.5). Names are matched
ignoring case, spaces and underscores.

How the drawing is read:
  plot          largest closed polyline on a `plot` layer → site boundary
  roads         `road` polylines; the width is the number at the start of their text
                ("10.50 m wd. Main Road"), else measured across the polygon
  footprint     largest `footprint` polyline (_PropWork)
  floors        each `floor` frame and its name: "Ground Floor Plan", "First Floor Plan",
                "TYPICAL-2-4 FLOOR PLAN", "TYPICAL-1,4 FLOOR PLAN", "TYPICAL-2&3 FLOOR PLAN".
                Everything inside a frame belongs to that floor (and to each typical floor).
                Floor content is shifted so its built-up outline lines up with the footprint.
  heights       `floor_height` rectangles named like the floors (one per floor): floor-to-floor
                is the rectangle's height; elevations stack from the ground floor; a `ground`
                line below the ground floor gives the plinth
  rooms         `room` polylines; name = text inside; clear height = floor-to-floor − 0.15 m
                (a slab assumption, reported in the warnings: 2D drawings don't carry it)
  FSI           `fsi_*` polylines per floor → one area per use per level
  tenements     `carpet` polylines; name = text inside; commercial if inside a _CommFSI poly
  doors         `door` polylines: width = longer side; height unknown in plan (null); the rooms
                it joins from geometry; exit = on the floor's outer outline (inferred)
  stairs        `stair` polylines with tread lines inside: width = tread line length, tread =
                spacing, riser = floor-to-floor ÷ number of tread lines; same stair on several
                floors is merged
Anything the drawing doesn't say stays null (→ "can't verify" and a question), never guessed.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import ezdxf
import yaml
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from compliance.adapters.ifc import _coords, _f, _rooms_at, _tag_edges
from compliance.adapters.usage import guess
from compliance.config import REPO_ROOT

SLAB_M = 0.15
OUTER = "door on the floor's outer outline"
_ORD = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
        "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}  # fmt: skip
_UNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}  # $INSUNITS → metres
_WIDTH = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*m", re.I)


# Presentation layers every CAD office has and no rule reads (our convention, not PreDCR), matched
# on whole words: "A-WALL" and "WALL-HATCH" match, "A-AREA-ROOMS" does not.
_CONVENTION_IGNORE = {
    "wall", "walls", "hatch", "hatching", "swing", "glazing", "dim", "dims", "dimension",
    "dimensions", "text", "txt", "anno", "annotation", "furn", "furniture", "title", "titleblock",
    "grid", "defpoints", "viewport", "vport", "elev", "elevation", "tree", "trees", "centreline",
    "centerline", "landscape", "electrical", "plumbing",
}  # fmt: skip


def convention_role(layer: str) -> str | None:
    words = set(re.split(r"[\s_\-.]+", layer.lower())) - {""}
    return "ignore" if layer == "0" or words & _CONVENTION_IGNORE else None


def _key(layer: str) -> str:
    return re.sub(r"[\s_]+", "", layer).lower()


@lru_cache
def predcr_roles() -> dict[str, str]:
    path = REPO_ROOT / "rules" / "cities" / "pmc" / "data" / "predcr_layers.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    return {_key(x["name"]): x["role"] for x in data["layers"]}


def floor_numbers(name: str) -> list[int]:
    """'Ground Floor Plan' → [0]; 'TYPICAL-2-4 FLOOR PLAN' → [2, 3, 4]; 'TYPICAL-1,4' → [1, 4]."""
    s = name.lower()
    m = re.search(r"typical[\s-]*([\d,&\s-]+)", s)
    if m:
        out: list[int] = []
        for part in re.split(r"[,&]", m.group(1)):
            nums = [int(x) for x in re.findall(r"\d+", part)]
            if len(nums) == 2 and "-" in part:
                out.extend(range(nums[0], nums[1] + 1))
            else:
                out.extend(nums)
        return sorted(set(out))
    for word, n in _ORD.items():
        if re.search(rf"\b{word}\b", s):
            return [n]
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s*floor", s)
    return [int(m.group(1))] if m else []


@dataclass
class _Shape:
    poly: Polygon
    layer: str
    handle: str
    name: str | None = None


@dataclass
class _Drawing:
    scale: float
    polys: dict[str, list[_Shape]] = field(default_factory=lambda: defaultdict(list))
    lines: dict[str, list[tuple[LineString, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    texts: list[tuple[Point, str, str]] = field(default_factory=list)  # (where, text, role)
    layers: dict[str, dict[str, Any]] = field(default_factory=dict)  # layer → {role, count}


def _load(path: Path, roles: dict[str, str] | None, scale: float | None = None) -> _Drawing:
    doc = ezdxf.readfile(str(path))
    units = int(doc.header.get("$INSUNITS", 0) or 0)
    d = _Drawing(scale=scale or _UNITS.get(units, 1.0))
    custom = {_key(k): v for k, v in (roles or {}).items()}
    base = predcr_roles()

    def role_of(layer: str) -> str | None:
        k = _key(layer)
        return custom.get(k) or base.get(k) or convention_role(layer)

    s = d.scale
    for e in doc.modelspace():
        layer = e.dxf.layer
        info = d.layers.setdefault(
            layer,
            {"role": role_of(layer), "entities": 0, "closed": 0, "open": 0, "texts": 0,
             "blocks": 0, "samples": [], "areas": [], "outlines": []},
        )  # fmt: skip
        info["entities"] += 1
        role = info["role"]
        kind = e.dxftype()
        if kind in ("TEXT", "MTEXT"):
            txt = e.plain_text() if kind == "MTEXT" else e.dxf.text
            ins = e.dxf.insert
            d.texts.append((Point(ins.x * s, ins.y * s), txt.strip(), role or ""))
            info["texts"] += 1
            if txt.strip() and len(info["samples"]) < 6 and txt.strip() not in info["samples"]:
                info["samples"].append(txt.strip()[:40])
            continue
        if kind == "INSERT":
            info["blocks"] += 1
            if len(info["samples"]) < 6 and e.dxf.name not in info["samples"]:
                info["samples"].append(f"block:{e.dxf.name}"[:40])
            continue
        if kind == "LWPOLYLINE":
            is_closed = e.closed and len(e) >= 3
            info["closed" if is_closed else "open"] += 1
            if is_closed and len(info["areas"]) < 200:
                outline = Polygon([(x * s, y * s) for x, y in e.get_points("xy")])
                info["areas"].append(abs(outline.area))
                if outline.is_valid:
                    info["outlines"].append(outline)
        elif kind in ("LINE", "POLYLINE", "ARC", "CIRCLE"):
            info["open"] += 1
        if role in (None, "ignore"):
            continue
        if kind == "LWPOLYLINE":
            pts = [(p[0] * s, p[1] * s) for p in e.get_points("xy")]
            closed = e.closed
        elif kind == "POLYLINE":
            pts = [(v.dxf.location.x * s, v.dxf.location.y * s) for v in e.vertices]
            closed = e.is_closed
        elif kind == "LINE":
            pts = [(e.dxf.start.x * s, e.dxf.start.y * s), (e.dxf.end.x * s, e.dxf.end.y * s)]
            closed = False
        else:
            continue
        if closed and len(pts) >= 3:
            p = Polygon(pts)
            if p.is_valid and p.area > 1e-6:
                d.polys[role].append(_Shape(p, layer, e.dxf.handle))
        elif len(pts) >= 2:
            d.lines[role].append((LineString(pts), e.dxf.handle))
    # Unitless drawings in millimetres are common: a plot over 1 km² means the units were mm.
    if units == 0 and scale is None and d.polys.get("plot"):
        if max(x.poly.area for x in d.polys["plot"]) > 1e6:
            return _load(path, roles, 0.001)
    return d


def _name_inside(shape: _Shape, texts: list[tuple[Point, str, str]], role: str) -> str | None:
    inside = [(t, r) for p, t, r in texts if t and shape.poly.contains(p)]
    same = [t for t, r in inside if r == role]
    return (same or [t for t, _ in inside] or [None])[0]


def read(path: str | Path, roles: dict[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """(BuildingModel dict, warnings)."""
    path = Path(path)
    d = _load(path, roles)
    warnings: list[str] = []
    for role in ("room", "floor", "floor_height", "carpet", "road", "plot", "footprint"):
        for sh in d.polys.get(role, []):
            sh.name = _name_inside(sh, d.texts, role)

    # ---------------------------------------------------------------- site
    plots = sorted(d.polys.get("plot", []), key=lambda x: -x.poly.area)
    boundary = _coords(plots[0].poly) if plots else None
    if boundary is None:
        warnings.append("No plot boundary (_Main Plot): margins and FSI can't be checked.")
    edges = []
    for i, a in enumerate(boundary or []):
        b = boundary[(i + 1) % len(boundary)]
        edges.append({
            "id": f"e{i + 1}", "a": a, "b": b,
            "kind": _f(None), "road_width_m": _f(None), "road_width_basis": _f(None),
        })  # fmt: skip
    roads = []
    for r in d.polys.get("road", []):
        m = _WIDTH.match(r.name or "")
        roads.append((r.poly, {"Width": float(m.group(1)) if m else None}))
    _tag_edges(edges, roads)
    for e in edges:
        if e["kind"]["value"] == "road" and e["road_width_m"].get("note") == "CC_Road.Width":
            e["road_width_m"]["note"] = "road width written on the _Main Road text"

    fps = sorted(d.polys.get("footprint", []), key=lambda x: -x.poly.area)
    footprint = fps[0].poly if fps else None

    # ---------------------------------------------------------------- floors and heights
    floors = _floor_frames(d, warnings)
    if not floors:
        warnings.append("No _Floor frames: rooms, doors and stairs can't be placed on floors.")
    heights: dict[int, tuple[float, float]] = {}  # floor number → (bottom y, height)
    for sec in d.polys.get("floor_height", []):
        for n in floor_numbers(sec.name or ""):
            x0, y0, x1, y1 = sec.poly.bounds
            heights[n] = (y0, y1 - y0)
    all_nums = sorted({n for _, nums in floors for n in nums})
    ground_y = None
    if d.lines.get("ground"):
        ground_y = min(min(y for _, y in ln.coords) for ln, _ in d.lines["ground"])
    plinth = 0.0
    if ground_y is not None and 0 in heights:
        plinth = round(heights[0][0] - ground_y, 4)
    elev: dict[int, float] = {}
    z = plinth
    for n in all_nums:
        elev[n] = round(z, 4)
        if n in heights:
            z += heights[n][1]
        else:
            warnings.append(
                f"No _FloorInSection for floor {n}: its height and the building height are unknown."
            )
            z = math.nan
    top = all_nums[-1] if all_nums else None
    roof_top = (
        round(elev[top] + heights[top][1], 4)
        if top is not None and top in heights and not math.isnan(elev[top])
        else None
    )
    level_id = {n: f"L{n}" for n in all_nums}
    levels = [
        {"id": level_id[n], "source_id": None, "name": _level_name(n), "is_basement": n < 0,
         "elevation_m": elev[n] if not math.isnan(elev[n]) else 0.0}
        for n in all_nums
    ]  # fmt: skip

    # ---------------------------------------------------------------- per-floor content
    spaces, areas, doors, units = [], [], [], []
    stairs_by_spot: dict[tuple[int, int], dict[str, Any]] = {}
    slab_note = False
    shifts = _floor_shifts(d, floors, footprint, warnings)
    for fr, nums in floors:
        inside = {
            role: [
                s for s in d.polys.get(role, []) if fr.poly.contains(s.poly.representative_point())
            ]
            for role in ("room", "fsi_resi", "fsi_comm", "fsi_other", "carpet", "door", "stair")
        }
        # Line the floor up with the others and the footprint, so geometry is in plot coordinates.
        dx, dy, outline_parts = shifts[fr.handle]

        def moved(p: Polygon, dx: float = dx, dy: float = dy) -> Polygon:
            return translate(p, dx, dy)

        # The floor's outer edge (for exit doors) is all its rooms, stilt parking included.
        room_parts = [moved(s.poly) for s in inside["room"]] or [moved(p) for p in outline_parts]
        outline = unary_union(room_parts) if room_parts else None
        if outline is not None and outline.geom_type == "MultiPolygon":
            outline = max(outline.geoms, key=lambda g: g.area)
        for n in nums:
            lv = level_id[n]
            h = heights.get(n, (0, None))[1]
            clear = round(h - SLAB_M, 4) if h else None
            slab_note = slab_note or clear is not None
            floor_spaces = []
            for r in inside["room"]:
                name = r.name or f"Room {r.handle}"
                poly = moved(r.poly)
                sp = {
                    "id": f"{lv}-{r.handle}", "source_id": r.handle, "name": name, "level_id": lv,
                    "usage": guess(name), "area_m2": round(poly.area, 4), "clear_height_m": clear,
                    "polygon": _coords(poly),
                }  # fmt: skip
                spaces.append(sp)
                floor_spaces.append(sp)
            for role, use in (
                ("fsi_resi", "residential"),
                ("fsi_comm", "commercial"),
                ("fsi_other", "other"),
            ):
                total = sum(s.poly.area for s in inside[role])
                if total:
                    areas.append({
                        "id": f"{lv}-{role}", "source_id": None, "scheme": f"PreDCR {role}",
                        "level_id": lv, "name": f"{use} built-up {_level_name(n)}",
                        "area_m2": round(total, 4),
                        "counts_to_far": _f(True, note="PreDCR FSI layer"),
                    })  # fmt: skip
            comm = unary_union([s.poly for s in inside["fsi_comm"]]) if inside["fsi_comm"] else None
            for c in inside["carpet"]:
                use = (
                    "commercial"
                    if comm is not None and comm.contains(c.poly.representative_point())
                    else "residential"
                )
                units.append({
                    "id": f"{lv}-{c.name or c.handle}", "source_id": c.handle,
                    "name": c.name or f"Tenement {c.handle}", "level_id": lv,
                    "carpet_area_m2": round(c.poly.area, 4),
                    "use": {"value": use, "source": "inferred", "confidence": 0.7,
                            "note": "from the FSI layer it sits in"},
                })  # fmt: skip
            for dr in inside["door"]:
                poly = moved(dr.poly)
                rect = poly.minimum_rotated_rectangle
                xs = list(rect.exterior.coords)
                sides = [math.dist(xs[i], xs[i + 1]) for i in range(2)]
                joins = _rooms_at(poly, floor_spaces)
                on_outline = outline is not None and outline.exterior.distance(poly.centroid) < 0.3
                doors.append({
                    "id": f"{lv}-{dr.handle}", "source_id": dr.handle, "level_id": lv,
                    "width_m": round(max(sides), 4), "height_m": None,
                    "is_exit": {"value": bool(on_outline), "source": "inferred", "confidence": 0.6,
                                "note": OUTER if on_outline else "internal door"},
                    "from_space_id": joins[0] if joins else None,
                    "to_space_id": joins[1] if len(joins) > 1 else None,
                })  # fmt: skip
            for st in inside["stair"]:
                treads = [
                    ln for ln, _ in d.lines.get("stair", []) if st.poly.buffer(0.01).contains(ln)
                ]
                width = statistics.median(ln.length for ln in treads) if treads else None
                tread = _spacing(treads)
                riser = round(h / len(treads), 4) if h and treads else None
                c = moved(st.poly).centroid
                spot = (round(c.x), round(c.y))
                s = stairs_by_spot.setdefault(spot, {
                    "id": f"ST{len(stairs_by_spot) + 1}", "source_id": st.handle,
                    "base_level_id": lv, "top_level_id": lv, "min_run_width_m": None,
                    "riser_m": None, "tread_m": None,
                    "is_exit": {"value": True, "source": "inferred", "confidence": 0.6,
                                "note": "staircases assumed to be exit routes"},
                    "_nums": [],
                })  # fmt: skip
                s["_nums"].append(n)
                if width is not None:
                    s["min_run_width_m"] = round(min(width, s["min_run_width_m"] or width), 4)
                if tread is not None:
                    s["tread_m"] = round(min(tread, s["tread_m"] or tread), 4)
                if riser is not None:
                    s["riser_m"] = round(max(riser, s["riser_m"] or riser), 4)
    stairs = []
    for s in stairs_by_spot.values():
        nums = sorted(s.pop("_nums"))
        s["base_level_id"], s["top_level_id"] = level_id[nums[0]], level_id[nums[-1]]
        stairs.append(s)
    if slab_note:
        warnings.append(
            f"Room clear heights assume a {SLAB_M * 1000:.0f} mm slab: "
            "floor-to-floor from the section minus the slab."
        )
    if not d.polys.get("door"):
        warnings.append("No _Door polylines: door widths can't be checked.")

    has_resi = bool(d.polys.get("fsi_resi"))
    has_comm = bool(d.polys.get("fsi_comm"))
    project = {
        "name": path.stem.replace("_", " "),
        "location": _f(None, note="2D drawings carry no location: set it in the web app"),
        "authority_id": _f(None, note="resolved by the server from the location"),
        "rulesets": _f(None, note="resolved by the server from the location"),
        "occupancy": (
            {"value": {"group": "A", "subdivision": None}, "source": "inferred", "confidence": 0.6,
             "note": "_ResiFSI layer present"} if has_resi else _f(None)
        ),
        "zone": _f(None),
        "congested_area": _f(None),
        "special": {
            k: _f(None)
            for k in ("heritage", "coastal", "airport_zone", "ht_line", "railway",
                      "river_flood_line", "hill_slope_bdp", "defence_vicinity",
                      "metro_rail_within_20m")
        },
        "building_type": (
            {"value": "mixed_use", "source": "inferred", "confidence": 0.6,
             "note": "both _ResiFSI and _CommFSI present"} if has_resi and has_comm else _f(None)
        ),
        "overlays": {
            k: _f(None) for k in ("nearest_metro_station", "metro_tod", "plot_share_in_tod")
        },
    }  # fmt: skip
    road_edges = sum(1 for e in edges if e["kind"]["value"] == "road")
    model = {
        "schema_version": "1.0",
        "meta": {
            "source_kind": "dxf",
            "source_file": path.name,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool_version": f"ezdxf {ezdxf.__version__}",
        },
        "project": project,
        "site": {
            "boundary": boundary,
            "plot_area_declared_m2": _f(None),
            "is_corner_plot": (
                {
                    "value": road_edges >= 2,
                    "source": "inferred",
                    "confidence": 0.7,
                    "note": "roads drawn on two or more sides",
                }
                if road_edges
                else _f(None)
            ),
            "ground_level_m": 0.0 if ground_y is not None else None,
            "edges": edges,
        },  # fmt: skip
        "levels": levels,
        "building": {
            "footprint": _coords(footprint) if footprint is not None else None,
            "roof_top_m": roof_top,
            "highest_point_m": roof_top,
        },
        "spaces": spaces,
        "areas": areas,
        "stairs": stairs,
        "doors": doors,
        "units": units,
    }
    if warnings:
        model["_notes"] = warnings
    return model, warnings


def layer_report(
    path: str | Path,
    roles: dict[str, str] | None = None,
    suggested: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every layer: role (null = not understood yet), where the role came from (predcr | user |
    suggested, the last shown dashed until confirmed), and its contents for the web table."""
    user = {_key(k): v for k, v in (roles or {}).items()}
    sugg = {_key(k): v for k, v in (suggested or {}).items()}
    merged = {**{k: v["role"] for k, v in (suggested or {}).items()}, **(roles or {})}
    d = _load(Path(path), merged)
    base = predcr_roles()
    out = []
    for name, info in sorted(d.layers.items()):
        k = _key(name)
        source = (
            "user" if k in user
            else "suggested" if k in sugg
            else "predcr" if k in base
            else "convention" if convention_role(name)
            else None
        )  # fmt: skip
        row = {"layer": name, "role": info["role"], "source": source, "entities": info["entities"]}
        if source == "suggested":
            row["confidence"] = sugg[k].get("confidence")
        out.append(row)
    return out


def layer_profiles(path: str | Path, roles: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """What is on each layer, for the layer-role agent (P10.3): counts, sample texts, areas."""
    d = _load(Path(path), roles)
    # Comparative facts a layer name alone can't give: how its biggest outline ranks against the
    # other layers', and whether all its outlines sit inside that biggest outline of another layer.
    # Floor frames (they hold floor names) are left out of the ranking, as sheets are big.
    framed = {
        n
        for n, i in d.layers.items()
        if any(floor_numbers(s) for s in i["samples"]) and i["closed"]
    }
    biggest = sorted(
        ((max(i["areas"]), n) for n, i in d.layers.items() if i["areas"] and n not in framed),
        reverse=True,
    )
    rank = {n: k + 1 for k, (_, n) in enumerate(biggest)}

    def contains(name: str) -> list[str]:
        """Other layers with at least one outline inside one of this layer's outlines."""
        mine = d.layers[name]["outlines"][:50]
        hits = []
        for other, oi in d.layers.items():
            if other == name or not oi["outlines"]:
                continue
            theirs = [o.buffer(-0.01) for o in oi["outlines"][:50]]
            if any(
                m.area > t.area and m.contains(t) for m in mine for t in theirs if not t.is_empty
            ):
                hits.append(other)
        return sorted(hits)[:8]

    out = []
    for name, info in sorted(d.layers.items()):
        areas = sorted(info["areas"])
        out.append({
            "layer": name, "role": info["role"], "closed_polylines": info["closed"],
            "open_lines": info["open"], "texts": info["texts"], "blocks": info["blocks"],
            "samples": info["samples"],
            "median_area_m2": round(statistics.median(areas), 2) if areas else None,
            "max_area_m2": round(areas[-1], 2) if areas else None,
            "largest_outline_rank": rank.get(name),
            "holds_floor_names": name in framed,
            "contains_outlines_of": contains(name) if info["outlines"] else [],
        })  # fmt: skip
    return out


def _floor_frames(d: _Drawing, warnings: list[str]) -> list[tuple[_Shape, list[int]]]:
    """Each floor plan's frame and the floor numbers it stands for (typicals → several)."""
    if not d.polys.get("floor") and d.polys.get("room"):
        d.polys["floor"] = _auto_frames(d, warnings)
    floors = []
    for fr in d.polys.get("floor", []):
        nums = floor_numbers(fr.name or "")
        if not nums:
            warnings.append(
                f"Floor frame '{fr.name or fr.handle}' has no floor name I understand; skipped."
            )
            continue
        floors.append((fr, nums))
    return floors


def _floor_shift(
    d: _Drawing, fr: _Shape, footprint: Polygon | None
) -> tuple[float, float, list[Polygon]]:
    """How far to move a floor plan so its built-up outline sits on the site footprint."""
    inside = [
        s.poly
        for r in ("fsi_resi", "fsi_comm", "fsi_other")
        for s in d.polys.get(r, [])
        if fr.poly.contains(s.poly.representative_point())
    ] or [
        s.poly for s in d.polys.get("room", []) if fr.poly.contains(s.poly.representative_point())
    ]
    if not inside or footprint is None:
        return 0.0, 0.0, inside
    ox0, oy0, _, _ = unary_union(inside).bounds
    fx0, fy0, _, _ = footprint.bounds
    return fx0 - ox0, fy0 - oy0, inside


_CORE_NAME = re.compile(r"\b(stair|staircase|lift|elevator)s?\b", re.IGNORECASE)


def _core(d: _Drawing, fr: _Shape) -> Point | None:
    """Where a floor's stair / lift core is. The core stands in the same place on every floor."""

    def inside(s: _Shape) -> bool:
        return fr.poly.contains(s.poly.representative_point())

    # stair outlines and rooms named stair / lift together, so every floor measures the same thing
    parts = [s.poly for s in d.polys.get("stair", []) if inside(s)] + [
        s.poly for s in d.polys.get("room", []) if inside(s) and _CORE_NAME.search(s.name or "")
    ]
    return unary_union(parts).centroid if parts else None


def _floor_shifts(
    d: _Drawing,
    floors: list[tuple[_Shape, list[int]]],
    footprint: Polygon | None,
    warnings: list[str],
) -> dict[str, tuple[float, float, list[Polygon]]]:
    """How far to move each floor plan into plot coordinates.

    One floor, the reference, is lined up with the building footprint on the site plan: the one
    whose outline matches it best once their corners meet. Every other floor is lined up with the
    reference on the stair / lift core, so a floor that projects or steps back still lands right.
    A floor without a core (or whose core match is far from its outline) falls back to the corner.
    """
    corner = {fr.handle: _floor_shift(d, fr, footprint) for fr, _ in floors}
    if len(floors) < 2:
        return corner

    def fit(fr: _Shape) -> float:
        dx, dy, parts = corner[fr.handle]
        if footprint is None or not parts:
            return 0.0
        outline = translate(unary_union(parts), dx, dy)
        union = outline.union(footprint).area
        return outline.intersection(footprint).area / union if union else 0.0

    nums = {fr.handle: ns for fr, ns in floors}
    ref = max((fr for fr, _ in floors), key=lambda f: (fit(f), -min(nums[f.handle] or [0])))
    ref_core = _core(d, ref)
    if ref_core is None:
        warnings.append(
            "Floors lined up by their outline's corner: no stair or lift found to line them up on."
        )
        return corner
    rdx, rdy, _ = corner[ref.handle]
    target = (ref_core.x + rdx, ref_core.y + rdy)
    out, by_core, by_corner = dict(corner), [], []
    for fr, _ in floors:
        if fr is ref:
            continue
        core = _core(d, fr)
        dx, dy, parts = corner[fr.handle]
        if core is None:
            by_corner.append(fr.name or fr.handle)
            continue
        cdx, cdy = target[0] - core.x, target[1] - core.y
        # a core match far from the outline match means the cores aren't the same core
        span = max(fr.poly.bounds[2] - fr.poly.bounds[0], fr.poly.bounds[3] - fr.poly.bounds[1])
        if math.hypot(cdx - dx, cdy - dy) > span * 0.25:
            by_corner.append(fr.name or fr.handle)
            continue
        out[fr.handle] = (cdx, cdy, parts)
        by_core.append(fr.name or fr.handle)
    if by_core:
        warnings.append(
            f"Floors lined up on the stair / lift core with {ref.name or 'the reference floor'} "
            f"(matched to the building outline): {', '.join(by_core)}."
        )
    if by_corner:
        warnings.append(
            "Lined up by the outline's corner (no matching stair or lift): "
            + ", ".join(by_corner)
            + ". Check these floors in the plan view."
        )
    return out


# Drawing classes for the web plan view (P10.5): how each layer is drawn, never what it means.
_SKIP_ROLES = {"fsi_resi", "fsi_comm", "fsi_other", "carpet", "floor", "floor_height", "ground",
               "plot", "road", "footprint"}  # fmt: skip


def _draw_class(layer: str, role: str | None, kind: str) -> str | None:
    if role in _SKIP_ROLES:
        return None
    words = set(re.split(r"[\s_\-.]+", layer.lower()))
    if kind in ("TEXT", "MTEXT"):
        return "text"
    if kind == "HATCH" or words & {"hatch", "hatching"}:
        return "fill"
    if words & {"wall", "walls"}:
        return "wall"
    if role == "door" or words & {"swing", "door", "doors"}:
        return "door"
    if role == "window" or words & {"glazing", "window", "windows"}:
        return "window"
    if role == "stair" or "stair" in layer.lower():
        return "stair"
    if role == "room":
        return "room"
    if words & {"dim", "dims", "dimension", "dimensions"}:
        return "dim"
    if role == "parking" or words & {"furn", "furniture"}:
        return "furniture"
    if layer.lower() in ("_site plan", "_section", "_floor") or words & {"title", "titleblock"}:
        return None
    return "anno"


def drawing(path: str | Path, roles: dict[str, str] | None = None) -> dict[str, Any]:
    """The drawing itself, per floor plan, as flat vector data in plot coordinates (aligned the
    same way as the model): {floors: [{nums, name, paths: {class: [[x, y, x, y, …], …]},
    fills: [[…]], texts: [[x, y, height, rotation, text, class]]}]}."""
    from ezdxf import path as ezpath

    path = Path(path)
    d = _load(path, roles)
    for sh in d.polys.get("floor", []):
        sh.name = _name_inside(sh, d.texts, "floor")
    for sh in d.polys.get("room", []):
        sh.name = _name_inside(sh, d.texts, "room")
    frames = _floor_frames(d, [])
    fps = sorted(d.polys.get("footprint", []), key=lambda x: -x.poly.area)
    footprint = fps[0].poly if fps else None
    by_frame = _floor_shifts(d, frames, footprint, [])
    shifts = [(fr, nums, by_frame[fr.handle][:2]) for fr, nums in frames]
    boxes = [(fr.poly.bounds, i) for i, (fr, _, _) in enumerate(shifts)]

    doc = ezdxf.readfile(str(path))
    s = d.scale
    out = [
        {"nums": nums, "name": fr.name, "paths": {}, "fills": [], "texts": []}
        for fr, nums, _ in shifts
    ]

    def which(x: float, y: float) -> int | None:
        for (x0, y0, x1, y1), i in boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def flat(points, i) -> list[float]:
        dx, dy = shifts[i][2]
        return [v for x, y in points for v in (round(x * s + dx, 3), round(y * s + dy, 3))]

    def emit(e, layer: str) -> None:
        kind = e.dxftype()
        if kind in ("INSERT", "DIMENSION"):
            try:
                for v in e.virtual_entities():
                    emit(v, layer if v.dxf.layer == "0" else v.dxf.layer)
            except Exception:  # noqa: BLE001 - a block we can't explode is just not drawn
                pass
            return
        info = d.layers.get(layer)
        cls = _draw_class(layer, info["role"] if info else None, kind)
        if cls is None:
            return
        if kind in ("TEXT", "MTEXT"):
            ins = e.dxf.insert
            i = which(ins.x * s, ins.y * s)
            if i is None:
                return
            txt = (e.plain_text() if kind == "MTEXT" else e.dxf.text).strip()
            if not txt:
                return
            h = (e.dxf.char_height if kind == "MTEXT" else e.dxf.height) * s
            (x, y) = flat([(ins.x, ins.y)], i)
            rot = round(e.dxf.get("rotation", 0.0), 1)
            tcls = "room" if info and info["role"] == "room" else "text"
            out[i]["texts"].append([x, y, round(h, 3), rot, txt[:60], tcls])
            return
        try:
            paths = ezpath.from_hatch(e) if kind == "HATCH" else [ezpath.make_path(e)]
        except Exception:  # noqa: BLE001 - entity types we don't draw
            return
        for p in paths:
            pts = [(v.x, v.y) for v in p.flattening(0.02)]
            if len(pts) < 2:
                continue
            i = which(*(c * s for c in pts[0]))
            if i is None:
                continue
            if kind == "HATCH":
                out[i]["fills"].append(flat(pts, i))
            else:
                out[i]["paths"].setdefault(cls, []).append(flat(pts, i))

    for e in doc.modelspace():
        emit(e, e.dxf.layer)
    return {"floors": out}


def _auto_frames(d: _Drawing, warnings: list[str]) -> list[_Shape]:
    """No _Floor frames: find the floor plans as clusters of room outlines (plans sit apart in
    model space) and name each from the nearest floor-name text. Unnamed plans are numbered left
    to right, and the warnings say so."""
    gap = 3.0  # metres between plans
    parts = [s.poly.envelope.buffer(gap / 2) for s in d.polys["room"]]
    merged = unary_union(parts)
    clusters = sorted(
        (g.buffer(-gap / 2 + 1.0) for g in getattr(merged, "geoms", [merged])),
        key=lambda g: g.bounds[0],
    )
    named = [(p, t) for p, t, _ in d.texts if floor_numbers(t)]
    frames, used, unnamed = [], set(), []
    for k, c in enumerate(clusters):
        frame = c.envelope
        reach = max(frame.bounds[3] - frame.bounds[1], frame.bounds[2] - frame.bounds[0]) * 0.35
        near = sorted((frame.distance(p), t) for p, t in named if frame.distance(p) <= reach)
        name = next((t for _, t in near if t not in used), None)
        if name is None:
            unnamed.append(k)
        else:
            used.add(name)
        frames.append(_Shape(frame, "(auto floor frame)", f"auto-{k + 1}", name))
    if unnamed:
        taken = {n for f in frames if f.name for n in floor_numbers(f.name)}
        free = (n for n in range(0, 100) if n not in taken)
        for k in unnamed:
            n = next(free)
            frames[k].name = f"{_level_name(n)} Plan"
        warnings.append(
            f"{len(unnamed)} floor plan(s) had no floor-name title nearby; numbered left to right. "
            "Add titles like 'GROUND FLOOR PLAN' or draw _Floor frames to be sure."
        )
    warnings.append(
        f"No _Floor frames: found {len(frames)} floor plan(s) from the room outlines "
        f"({', '.join(f.name or '?' for f in frames)})."
    )
    return frames


def _spacing(treads: list[LineString]) -> float | None:
    """Typical distance between neighbouring parallel tread lines (the going)."""
    if len(treads) < 2:
        return None
    (x0, y0), (x1, y1) = treads[0].coords[0], treads[0].coords[-1]
    ln = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / ln, (x1 - x0) / ln  # perpendicular to the treads
    offs = sorted(round(ln_.centroid.x * nx + ln_.centroid.y * ny, 4) for ln_ in treads)
    gaps = [b - a for a, b in zip(offs, offs[1:], strict=False) if 0.15 < b - a < 0.5]
    return round(statistics.median(gaps), 4) if gaps else None


def _level_name(n: int) -> str:
    names = {v: k for k, v in _ORD.items()}
    return f"{names[n].title()} Floor" if n in names else f"Floor {n}"
