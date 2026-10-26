"""Draw the demo buildings as 2D DXF files in the PreDCR layer standard (P10.2).

Usage: just make-samples   (after the IFC samples; writes fixtures/dxf/*.dxf and web/public/samples/)

What a PreDCR user draws, and what this script draws from fixtures/models/<name>.json:
  layout      _Main Plot (plot), _Main Road (road strip, text "10.50 m wd. Main Road"), _PropWork
  floors      one _Floor frame per distinct floor plan, named "Ground Floor Plan", "First Floor Plan",
              "TYPICAL-2-4 FLOOR PLAN"; inside it _Room (+ name), _Door, _Staircase (+ tread lines),
              _ResiFSI / _CommFSI (built-up per floor) and _Carpet area (+ tenement name)
  section     one _FloorInSection rectangle per floor, as tall as floor-to-floor, named per floor;
              _Ground Level line under the ground floor
Layer names follow rules/cities/pmc/data/predcr_layers.yaml (from the official PreDCR manual).
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
from collections import defaultdict

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from compliance.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import dxf_detail as detail  # noqa: E402

NAMES = ["demo_apartment", "demo_house"]
OUT = REPO_ROOT / "fixtures" / "dxf"
WEB = REPO_ROOT / "web" / "public" / "samples"
WEB_SAMPLES = {"demo_house"}  # the one DXF the web app offers; the rest are test fixtures
ORDINAL = ["Ground", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth",
           "Ninth", "Tenth", "Eleventh", "Twelfth"]  # fmt: skip
WALL = 0.23


def poly(msp, pts, layer, closed=True):
    msp.add_lwpolyline(
        [tuple(map(float, p)) for p in pts], close=closed, dxfattribs={"layer": layer}
    )


def text(msp, s, at, layer, h=0.35):
    t = msp.add_text(s, height=h, dxfattribs={"layer": layer})
    t.set_placement(at, align=TextEntityAlignment.MIDDLE_CENTER)


def coords(g):
    return [tuple(c) for c in list(g.exterior.coords)[:-1]]


def unit_of(space_name: str) -> str | None:
    """'Flat 101 Living' → 'Flat 101'; 'Shop 1' → 'Shop 1'."""
    words = space_name.split()
    if len(words) >= 2 and words[0] in ("Flat", "Shop"):
        return " ".join(words[:2])
    return None


def room_label(name: str) -> str:
    """'Flat 205 Bedroom' → 'Bedroom' (the flat's name is on its carpet outline); 'Staircase L2' →
    'Staircase' (the floor is in the sheet title). Shops keep their name."""
    label = re.sub(r"^Flat\s+\d+\s+", "", name)
    return re.sub(r"\s+L\d+$", "", label)


def signature(spaces):
    return tuple(sorted((tuple(map(tuple, s["polygon"])), s["usage"]["value"]) for s in spaces))


def floor_names(groups):
    out = []
    for nums in groups:
        if len(nums) == 1:
            out.append(f"{ORDINAL[nums[0]]} Floor Plan")
        else:
            out.append(f"TYPICAL-{nums[0]}-{nums[-1]} FLOOR PLAN")
    return out


def build(name: str) -> None:
    m = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    detail.setup(doc)

    # ---------------------------------------------------------------- layout
    b = m["site"]["boundary"]
    poly(msp, b, "_Main Plot")
    text(msp, "PLOT", (sum(p[0] for p in b) / len(b), sum(p[1] for p in b) / len(b)), "_Main Plot")
    for e in m["site"]["edges"]:
        if e["kind"]["value"] != "road":
            continue
        (ax, ay), (bx, by) = e["a"], e["b"]
        w = e["road_width_m"]["value"]
        ln = math.hypot(bx - ax, by - ay)
        nx, ny = (by - ay) / ln, -(bx - ax) / ln
        strip = [(ax, ay), (bx, by), (bx + nx * w, by + ny * w), (ax + nx * w, ay + ny * w)]
        poly(msp, strip, "_Main Road")
        text(
            msp,
            f"{w:.2f} m wd. Main Road",
            ((ax + bx) / 2 + nx * w / 2, (ay + by) / 2 + ny * w / 2),
            "_Main Road",
        )
    fp = m["building"]["footprint"]
    poly(msp, fp, "_PropWork")
    text(msp, "A", Polygon(fp).centroid.coords[0], "_PropWork")
    detail.site(msp, m)

    # ---------------------------------------------------------------- floors (grouped into typicals)
    levels = sorted(m["levels"], key=lambda lv: lv["elevation_m"])
    by_level = defaultdict(list)
    for sp in m["spaces"]:
        by_level[sp["level_id"]].append(sp)
    groups: list[list[int]] = []
    sigs: list[tuple] = []
    for i, lv in enumerate(levels):
        sig = signature(by_level[lv["id"]])
        if groups and sigs[-1] == sig and groups[-1][-1] == i - 1 and i > 1:
            groups[-1].append(i)
        else:
            groups.append([i])
            sigs.append(sig)
    names = floor_names(groups)

    W = max(p[0] for p in b)
    fpx = [p[0] for p in fp]
    fpy = [p[1] for p in fp]
    fw = max(fpx) - min(fpx)
    units_by_id = {u["name"].split(" (")[0]: u for u in m["units"]}
    stair = m["stairs"][0] if m["stairs"] else None
    for k, (nums, fname) in enumerate(zip(groups, names, strict=True)):
        lv = levels[nums[0]]
        dx = W + 15 + k * (fw + 15) - min(fpx)

        def T(p, dx=dx):
            return (p[0] + dx, p[1])

        spaces = by_level[lv["id"]]
        frame = [T((min(fpx) - 2.5, min(fpy) - 4.2)), T((max(fpx) + 1.5, min(fpy) - 4.2)),
                 T((max(fpx) + 1.5, max(fpy) + 1.5)), T((min(fpx) - 2.5, max(fpy) + 1.5))]  # fmt: skip
        poly(msp, frame, "_Floor")
        text(msp, fname, ((frame[0][0] + frame[1][0]) / 2, frame[0][1] + 1.0), "_Floor", 0.6)

        for sp in spaces:
            poly(msp, [T(p) for p in sp["polygon"]], "_Room")

        # Built-up area per floor: rooms by use; parking (stilt) is not FSI.
        comm = [Polygon(s["polygon"]) for s in spaces if s["usage"]["value"] == "retail"]
        resi = [
            Polygon(s["polygon"])
            for s in spaces
            if s["usage"]["value"] not in ("retail", "parking")
        ]
        for layer, parts in (("_CommFSI", comm), ("_ResiFSI", resi)):
            if not parts:
                continue
            u = unary_union(parts)
            for g in getattr(u, "geoms", [u]):
                poly(msp, [T(p) for p in coords(g)], layer)

        # Tenement carpet areas: the unit's rooms, inset so the area equals the declared carpet.
        rooms_of = defaultdict(list)
        for s in spaces:
            if u := unit_of(s["name"]):
                rooms_of[u].append(Polygon(s["polygon"]))
        for uname, parts in rooms_of.items():
            unit = units_by_id.get(uname)
            if unit is None or unit["carpet_area_m2"] is None:
                continue
            u = unary_union(parts)
            target = unit["carpet_area_m2"]
            lo, hi = 0.0, 1.0
            for _ in range(40):
                mid = (lo + hi) / 2
                if u.buffer(-mid, join_style=2).area > target:
                    lo = mid
                else:
                    hi = mid
            g = u.buffer(-lo, join_style=2)
            g = max(getattr(g, "geoms", [g]), key=lambda x: x.area)
            poly(msp, [T(p) for p in coords(g)], "_Carpet area")
            # Tenement name low in the carpet outline, clear of the room labels (kept inside it).
            x0c, y0c, x1c, y1c = g.bounds
            spot = Point((x0c + x1c) / 2, y0c + 0.5)
            if not g.contains(spot):
                spot = g.representative_point()
            text(msp, unit["name"].split(" (")[0], T((spot.x, spot.y)), "_Carpet area", 0.3)

        # Doors: a wall-thick rectangle centred on the edge the two rooms share.
        polys = {s["id"]: Polygon(s["polygon"]) for s in spaces}
        outline = unary_union(list(polys.values()))
        door_lines = []
        for d in (d for d in m["doors"] if d["level_id"] == lv["id"]):
            a = polys.get(d["from_space_id"])
            if a is None:
                continue
            if d["to_space_id"]:
                shared = a.boundary.intersection(polys[d["to_space_id"]].boundary)
            else:
                shared = a.boundary.intersection(outline.boundary)
            parts = [g for g in getattr(shared, "geoms", [shared])
                     if g.geom_type == "LineString" and not g.is_empty and g.length > 0.05]  # fmt: skip
            if not parts:
                continue
            line = (
                min(parts, key=lambda g: (round(g.centroid.y, 3), -g.length))
                if not d["to_space_id"]
                else max(parts, key=lambda g: g.length)
            )
            (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
            ln = math.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            hw, ht = d["width_m"] / 2, WALL / 2
            rect = [(mx - ux * hw - uy * ht, my - uy * hw + ux * ht), (mx + ux * hw - uy * ht, my + uy * hw + ux * ht),
                    (mx + ux * hw + uy * ht, my + uy * hw - ux * ht), (mx - ux * hw + uy * ht, my - uy * hw - ux * ht)]  # fmt: skip
            poly(msp, [T(p) for p in rect], "_Door")
            door_lines.append((line, d["width_m"], a))

        # Staircase: the stair room with one tread line per riser, in two flights.
        st = next((s for s in spaces if s["usage"]["value"] == "stair"), None)
        if stair and st and nums[0] < len(levels) - 1:
            sx = [p[0] for p in st["polygon"]]
            sy = [p[1] for p in st["polygon"]]
            poly(msp, [T(p) for p in st["polygon"]], "_Staircase")
            rise = levels[nums[0] + 1]["elevation_m"] - lv["elevation_m"]
            n = math.ceil(rise / stair["riser_m"] - 1e-9)
            w, t = stair["min_run_width_m"], stair["tread_m"]
            n1 = math.ceil(n / 2)
            for i in range(n):
                if i < n1:
                    xa, xb, y = min(sx) + 0.05, min(sx) + 0.05 + w, min(sy) + 0.3 + i * t
                else:
                    xa, xb, y = max(sx) - 0.05 - w, max(sx) - 0.05, min(sy) + 0.3 + (n - i) * t
                poly(msp, [T((xa, y)), T((xb, y))], "_Staircase", closed=False)
            # Walking line with an arrow and "UP", as drawn on plans.
            xa = min(sx) + 0.05 + w / 2
            xb = max(sx) - 0.05 - w / 2
            y_lo, y_hi = min(sy) + 0.3, min(sy) + 0.3 + (n1 - 1) * t
            poly(msp, [T((xa, y_lo)), T((xa, y_hi + 0.4)), T((xb, y_hi + 0.4)), T((xb, y_lo + 0.4))], "ANNO", closed=False)
            poly(msp, [T((xb - 0.12, y_lo + 0.65)), T((xb, y_lo + 0.4)), T((xb + 0.12, y_lo + 0.65))], "ANNO", closed=False)
            text(msp, "UP", T((xa, y_lo - 0.2)), "ANNO", 0.2)

        detail.floor(msp, spaces, door_lines, T, frame, fname, name_of=room_label)

    # ---------------------------------------------------------------- section: floor heights
    sx0 = W + 15 + len(groups) * (fw + 15) + 5
    roof = m["building"]["roof_top_m"]
    for i, lv in enumerate(levels):
        top = levels[i + 1]["elevation_m"] if i + 1 < len(levels) else roof
        z0 = lv["elevation_m"]
        poly(msp, [(sx0, z0), (sx0 + 12, z0), (sx0 + 12, top), (sx0, top)], "_FloorInSection")
        text(msp, f"{ORDINAL[i]} Floor Plan", (sx0 + 6, (z0 + top) / 2), "_FloorInSection", 0.3)
    poly(msp, [(sx0 - 3, 0.0), (sx0 + 15, 0.0)], "_Ground Level", closed=False)
    detail.section(msp, levels, roof, sx0)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.dxf"
    doc.saveas(path)
    if name in WEB_SAMPLES:
        WEB.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, WEB / path.name)
    print(f"wrote {path.relative_to(REPO_ROOT).as_posix()} ({path.stat().st_size // 1024} KB, "
          f"floors: {', '.join(names)})")  # fmt: skip
    if name in OFFICE_VARIANTS:
        office(doc, m)
        path = OUT / f"{name}_office.dxf"
        doc.saveas(path)
        print(f"wrote {path.relative_to(REPO_ROOT).as_posix()} (office layer names, for P10.3)")


# The same drawing as many offices name it, plus layers a checker must ignore (P10.3 tests).
OFFICE_VARIANTS = {"demo_house"}
OFFICE_NAMES = {
    "_Main Plot": "SITE BOUNDARY", "_Main Road": "ROAD", "_PropWork": "BUILDING OUTLINE",
    "_Floor": "SHEET FRAMES", "_Room": "A-AREA-ROOMS", "_Door": "A-DOOR", "_Staircase": "A-STAIR",
    "_ResiFSI": "BUA", "_CommFSI": "BUA-COMMERCIAL", "_Carpet area": "CARPET",
    "_FloorInSection": "SECTION-FLOOR HT", "_Ground Level": "SECTION-GL",
}  # fmt: skip
OFFICE_TRUTH = {**{v: k for k, v in OFFICE_NAMES.items()},
                "A-WALL": "ignore", "A-FURN": "ignore", "A-ANNO-DIMS": "ignore", "HATCH": "ignore"}  # fmt: skip


def office(doc, m) -> None:
    msp = doc.modelspace()
    for e in msp:
        if e.dxf.layer in OFFICE_NAMES:
            e.dxf.layer = OFFICE_NAMES[e.dxf.layer]
    # Noise a real drawing has: walls (closed outlines too), furniture blocks, dimensions, hatch.
    for sp in m["spaces"]:
        g = Polygon(sp["polygon"]).buffer(WALL / 2, join_style=2).difference(Polygon(sp["polygon"]))
        if g.geom_type == "Polygon":
            poly(msp, coords(g), "A-WALL")
    bed = doc.blocks.new(name="BED-DOUBLE")
    bed.add_lwpolyline([(0, 0), (1.8, 0), (1.8, 2.0), (0, 2.0)], close=True)
    for sp in m["spaces"]:
        if "Bed" in sp["name"]:
            c = Polygon(sp["polygon"]).centroid
            msp.add_blockref("BED-DOUBLE", (c.x - 0.9, c.y - 1.0), dxfattribs={"layer": "A-FURN"})
    for sp in m["spaces"][:6]:
        (x0, y0), (x1, _) = sp["polygon"][0], sp["polygon"][1]
        text(msp, f"{abs(x1 - x0) * 1000:.0f}", ((x0 + x1) / 2, y0 - 0.4), "A-ANNO-DIMS", 0.2)
    for sp in m["spaces"]:
        if sp["usage"]["value"] in ("bathroom", "wc"):
            poly(msp, sp["polygon"], "HATCH")


def main() -> int:
    for name in NAMES:
        build(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
