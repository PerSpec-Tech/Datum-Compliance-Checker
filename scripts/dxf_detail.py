"""Architectural detail for the sample DXFs (make_sample_dxf.py): what a real permit drawing has
beyond the PreDCR layers the checker reads. Everything here is on ordinary non-DCR layers (WALL,
HATCH, DOOR-SWING, GLAZING, DIMENSION, TEXT, FURNITURE, ANNO, TITLE, CENTRELINE), which AutoDCR
and our reader ignore; the PreDCR geometry stays exactly as before.
"""

from __future__ import annotations

import math

from ezdxf import const
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import linemerge, substring, unary_union

EXT_T, INT_T = 0.23, 0.115
LAYERS = {
    "WALL": 7, "HATCH": 8, "DOOR-SWING": 2, "GLAZING": 4, "DIMENSION": 3, "TEXT": 7,
    "FURNITURE": 8, "ANNO": 7, "TITLE": 7, "CENTRELINE": 1,
}  # fmt: skip
WINDOW_USES = {"living", "bedroom", "habitable", "kitchen", "retail", "office"}


def setup(doc) -> None:
    for name, color in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color, linetype="CENTER" if name == "CENTRELINE" else "Continuous")
    _blocks(doc)
    ds = doc.dimstyles.get("EZDXF")
    ds.dxf.dimtxt, ds.dxf.dimasz, ds.dxf.dimexe, ds.dxf.dimexo = 0.18, 0.12, 0.1, 0.1
    ds.dxf.dimlfac, ds.dxf.dimdec, ds.dxf.dimtad, ds.dxf.dimgap = 1000, 0, 1, 0.05
    ds.dxf.dimblk = "ARCHTICK"


def _text(msp, s, at, layer, h, align=TextEntityAlignment.MIDDLE_CENTER, rot=0.0):
    t = msp.add_text(s, height=h, rotation=rot, dxfattribs={"layer": layer})
    t.set_placement(at, align=align)


def _pl(msp, pts, layer, closed=True):
    msp.add_lwpolyline([tuple(map(float, p)) for p in pts], close=closed, dxfattribs={"layer": layer})


def _ring(g):
    return [tuple(c) for c in list(g.coords)[:-1]]


def _hatch(msp, geom, layer, pattern=None, scale=0.05, color=None):
    for g in getattr(geom, "geoms", [geom]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        h = msp.add_hatch(color=color or 8, dxfattribs={"layer": layer})
        if pattern:
            h.set_pattern_fill(pattern, scale=scale)
        h.paths.add_polyline_path(_ring(g.exterior), is_closed=True, flags=const.BOUNDARY_PATH_EXTERNAL)
        for hole in g.interiors:
            h.paths.add_polyline_path(_ring(hole), is_closed=True, flags=const.BOUNDARY_PATH_DEFAULT)


def _dim(msp, p1, p2, base, angle=0.0):
    msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="EZDXF",
                       dxfattribs={"layer": "DIMENSION"}).render()  # fmt: skip


# ---------------------------------------------------------------------------- blocks


def _blocks(doc) -> None:
    def blk(name):
        return doc.blocks.new(name=name) if name not in doc.blocks else None

    if (b := blk("BED-D")) is not None:  # 1.6 × 2.0, origin at the centre, head at +y
        b.add_lwpolyline([(-0.8, -1.0), (0.8, -1.0), (0.8, 1.0), (-0.8, 1.0)], close=True)
        for x in (-0.4, 0.4):
            b.add_lwpolyline([(x - 0.3, 0.6), (x + 0.3, 0.6), (x + 0.3, 0.9), (x - 0.3, 0.9)], close=True)
        b.add_line((-0.8, 0.3), (0.8, 0.3))
    if (b := blk("SOFA-3")) is not None:
        b.add_lwpolyline([(-1.05, -0.42), (1.05, -0.42), (1.05, 0.42), (-1.05, 0.42)], close=True)
        b.add_lwpolyline([(-0.85, -0.42), (0.85, -0.42), (0.85, 0.2), (-0.85, 0.2)], close=True)
        for x in (-0.28, 0.28):
            b.add_line((x, -0.42), (x, 0.2))
    if (b := blk("DINING-6")) is not None:
        b.add_lwpolyline([(-0.75, -0.45), (0.75, -0.45), (0.75, 0.45), (-0.75, 0.45)], close=True)
        for x in (-0.45, 0.0, 0.45):
            for y in (-0.7, 0.7):
                b.add_circle((x, y), 0.2)
    if (b := blk("WC")) is not None:
        b.add_lwpolyline([(-0.22, 0.25), (0.22, 0.25), (0.22, 0.42), (-0.22, 0.42)], close=True)
        b.add_ellipse((0, -0.02), major_axis=(0, 0.27), ratio=0.68)
    if (b := blk("BASIN")) is not None:  # counter-top basin: slab, bowl, drain and tap at the wall (+y)
        b.add_lwpolyline([(-0.28, -0.2), (0.28, -0.2), (0.28, 0.2), (-0.28, 0.2)], close=True)
        b.add_lwpolyline([(-0.19, -0.14), (0.19, -0.14), (0.19, 0.1), (-0.19, 0.1)], close=True)
        b.add_circle((0, -0.02), 0.025)
        b.add_line((0, 0.1), (0, 0.17))
    if (b := blk("CAR")) is not None:
        b.add_lwpolyline([(-1.25, -2.5), (1.25, -2.5), (1.25, 2.5), (-1.25, 2.5)], close=True)
        b.add_lwpolyline([(-0.85, -2.1), (0.85, -2.1), (0.85, 2.1), (-0.85, 2.1)], close=True)
        b.add_line((-0.85, 0.9), (0.85, 0.9))
        b.add_line((-0.85, -1.2), (0.85, -1.2))
    if (b := blk("NORTH")) is not None:
        b.add_circle((0, 0), 1.0)
        b.add_lwpolyline([(0, 1.0), (0.35, -0.7), (0, -0.35), (-0.35, -0.7)], close=True)
        b.add_text("N", height=0.5).set_placement((0, 1.5), align=TextEntityAlignment.MIDDLE_CENTER)


# ---------------------------------------------------------------------------- floors


def _straight_runs(line):
    pts = list(line.coords)
    runs, start = [], pts[0]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-9:
            runs.append((start, b))
            start = b
    runs.append((start, pts[-1]))
    return runs


def _lines(geom):
    """Any intersection result → merged line(s)."""
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "LineString"]
    if len(parts) <= 1:
        return parts[0] if parts else LineString()
    return linemerge(parts)


def _rect(mid, u, half_len, half_thk):
    (mx, my), (ux, uy) = mid, u
    nx, ny = -uy, ux
    return Polygon([
        (mx - ux * half_len - nx * half_thk, my - uy * half_len - ny * half_thk),
        (mx + ux * half_len - nx * half_thk, my + uy * half_len - ny * half_thk),
        (mx + ux * half_len + nx * half_thk, my + uy * half_len + ny * half_thk),
        (mx - ux * half_len + nx * half_thk, my - uy * half_len + ny * half_thk),
    ])  # fmt: skip


def floor(msp, spaces, doors, T, frame, title) -> None:
    """Walls (cut at openings, solid-hatched), door swings, windows, room labels, furniture,
    parking bays, dimensions and the sheet title for one floor plan. `doors` are
    (line, width, from_polygon) with the line on the edge the door sits on (plot coordinates)."""
    polys = {s["id"]: Polygon(s["polygon"]) for s in spaces}
    outline = unary_union(list(polys.values()))
    usage = {s["id"]: s["usage"]["value"] for s in spaces}

    # Wall centre lines: every room edge, straightened; outer walls thicker; no outer wall at stilt parking.
    lines = [LineString(list(p.exterior.coords)) for p in polys.values()]
    merged = linemerge(unary_union(lines))
    walls, outer_runs = [], []
    for g in getattr(merged, "geoms", [merged]):
        for a, b in _straight_runs(g):
            seg = LineString([a, b])
            if seg.length < 0.05:
                continue
            mid = seg.interpolate(0.5, normalized=True)
            exterior = outline.exterior.distance(mid) < 1e-6
            if exterior:
                inside = next((sid for sid, p in polys.items() if p.buffer(1e-6).contains(mid) or p.exterior.distance(mid) < 1e-6), None)
                if inside and usage[inside] == "parking":
                    continue
                outer_runs.append(seg)
            walls.append(seg.buffer((EXT_T if exterior else INT_T) / 2, cap_style=3, join_style=2))
    wall_body = unary_union(walls)

    cuts = []
    for line, width, from_poly in doors:
        (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
        ln = math.hypot(x1 - x0, y1 - y0) or 1.0
        u = ((x1 - x0) / ln, (y1 - y0) / ln)
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        cuts.append(_rect(mid, u, width / 2, 0.25))
        # Swing: hinge at one end, leaf into the room the door belongs to, quarter arc to the other end.
        hinge = (mid[0] - u[0] * width / 2, mid[1] - u[1] * width / 2)
        n = (-u[1], u[0])
        probe = Point(mid[0] + n[0] * 0.3, mid[1] + n[1] * 0.3)
        if not from_poly.contains(probe):
            n = (u[1], -u[0])
        leaf = (hinge[0] + n[0] * width, hinge[1] + n[1] * width)
        msp.add_line(T(hinge), T(leaf), dxfattribs={"layer": "DOOR-SWING"})
        a_open = math.degrees(math.atan2(u[1], u[0]))
        a_leaf = math.degrees(math.atan2(n[1], n[0]))
        cross = u[0] * n[1] - u[1] * n[0]
        start, end = (a_open, a_leaf) if cross > 0 else (a_leaf, a_open)
        msp.add_arc(T(hinge), width, start, end, dxfattribs={"layer": "DOOR-SWING"})

    # Windows: on the longest stretch of outer wall of each habitable room, kitchen or shop.
    door_lines = [d[0] for d in doors]
    windows = []
    for s in spaces:
        if s["usage"]["value"] not in WINDOW_USES:
            continue
        shared = _lines(polys[s["id"]].boundary.intersection(outline.boundary))
        runs = [
            LineString(r)
            for g in getattr(shared, "geoms", [shared]) if g.geom_type == "LineString" and not g.is_empty
            for r in _straight_runs(g)
        ]
        # A run that holds a door gets no window (the door is the opening on that wall).
        parts = [g for g in runs if all(g.distance(dl.interpolate(0.5, normalized=True)) > 0.05 for dl in door_lines)]
        if not parts:
            continue
        best = max(parts, key=lambda g: g.length)
        retail = s["usage"]["value"] == "retail"
        width = min(3.0 if retail else 1.5, best.length - 0.8)
        if width < 0.6:
            continue
        (x0, y0), (x1, y1) = best.coords[0], best.coords[-1]
        ln = best.length
        u = ((x1 - x0) / ln, (y1 - y0) / ln)
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        cuts.append(_rect(mid, u, width / 2, 0.25))
        opening = _rect(mid, u, width / 2, EXT_T / 2)
        windows.append(opening)
        _pl(msp, [T(p) for p in _ring(opening.exterior)], "_Window")
        for off in (-0.03, 0.03):
            a = (mid[0] - u[0] * width / 2 - u[1] * off, mid[1] - u[1] * width / 2 + u[0] * off)
            b = (mid[0] + u[0] * width / 2 - u[1] * off, mid[1] + u[1] * width / 2 + u[0] * off)
            msp.add_line(T(a), T(b), dxfattribs={"layer": "GLAZING"})

    body = wall_body.difference(unary_union(cuts)) if cuts else wall_body
    for g in getattr(body, "geoms", [body]):
        if g.geom_type != "Polygon":
            continue
        _pl(msp, [T(p) for p in _ring(g.exterior)], "WALL")
        for hole in g.interiors:
            _pl(msp, [T(p) for p in _ring(hole)], "WALL")
    _hatch(msp, _moved(body, T), "HATCH", color=8)

    # Room labels (the name stays on _Room for PreDCR; area and size on TEXT) and furniture.
    for s in spaces:
        p = polys[s["id"]]
        c = p.representative_point() if not p.contains(p.centroid) else p.centroid
        x0, y0, x1, y1 = p.bounds
        small = p.area < 6
        _text(msp, f"{p.area:.2f} m²", T((c.x, c.y - (0.22 if small else 0.32))), "TEXT", 0.14 if small else 0.18)
        if not small and abs(p.area - (x1 - x0) * (y1 - y0)) < 1e-6:
            _text(msp, f"{(x1 - x0):.2f} × {(y1 - y0):.2f}", T((c.x, c.y - 0.6)), "TEXT", 0.15)
        _furnish(msp, s["usage"]["value"], p, T, doors, windows)

    # Dimensions in mm: overall width and depth, and a chain along the front.
    ox0, oy0, ox1, oy1 = outline.bounds
    _dim(msp, T((ox0, oy0)), T((ox1, oy0)), T((ox0, oy0 - 1.6)))
    _dim(msp, T((ox0, oy0)), T((ox0, oy1)), T((ox0 - 1.2, oy0)), angle=90)
    front = sorted({round(x, 3) for p in polys.values() for x, y in p.exterior.coords if abs(y - oy0) < 1e-6})
    for xa, xb in zip(front, front[1:], strict=False):
        if xb - xa > 0.5:
            _dim(msp, T((xa, oy0)), T((xb, oy0)), T((xa, oy0 - 0.9)))

    # Sheet title under the frame.
    fx = (frame[0][0] + frame[1][0]) / 2
    _text(msp, "SCALE 1:100", (fx, frame[0][1] + 0.45), "TITLE", 0.25)
    del title


def _moved(geom, T):
    from shapely.affinity import translate

    dx, dy = T((0.0, 0.0))
    return translate(geom, dx, dy)


# Furniture footprints (width along the wall, depth into the room) with the back at the block's +y.
_SIZE = {"BED-D": (1.6, 2.0), "SOFA-3": (2.1, 0.84), "WC": (0.44, 0.69), "BASIN": (0.56, 0.4)}
# Block rotation that puts the back (+y) against each wall of the room's bounding box.
_WALL_ROT = {"top": 0.0, "left": 90.0, "bottom": 180.0, "right": 270.0}


def _door_zones(p, doors):
    """Where a room must stay clear: in front of each of its doors, as deep as the door is wide
    (the swing on one side, the way through on the other)."""
    zones = []
    for line, width, _ in doors:
        if p.exterior.distance(line.interpolate(0.5, normalized=True)) > 0.05:
            continue
        # `line` is the whole wall the door is on; the door itself is `width` wide at its middle.
        half = min(0.5, (width / 2 + 0.05) / max(line.length, 1e-9))
        opening = substring(line, 0.5 - half, 0.5 + half, normalized=True)
        zones.append(opening.buffer(width + 0.1, cap_style=2).intersection(p))
    return unary_union(zones) if zones else Polygon()


def _door_walls(p, doors):
    x0, y0, x1, y1 = p.bounds
    sides = set()
    for line, _, _ in doors:
        m = line.interpolate(0.5, normalized=True)
        if p.exterior.distance(m) > 0.05:
            continue
        for side, d in (("bottom", m.y - y0), ("top", y1 - m.y), ("left", m.x - x0), ("right", x1 - m.x)):
            if abs(d) < 0.05:
                sides.add(side)
    return sides


def _against(p, name, side, where):
    """A block's insertion point and footprint with its back on `side`, at `where` along the wall
    (0 = start, 0.5 = centred, 1 = end), clear of the wall by a few centimetres."""
    x0, y0, x1, y1 = p.bounds
    fw, fd = _SIZE[name]
    gap = INT_T / 2 + 0.02
    if side in ("top", "bottom"):
        x = x0 + gap + fw / 2 + where * max(0.0, (x1 - x0) - 2 * gap - fw)
        y = y1 - gap - fd / 2 if side == "top" else y0 + gap + fd / 2
        foot = box(x - fw / 2, y - fd / 2, x + fw / 2, y + fd / 2)
    else:
        y = y0 + gap + fw / 2 + where * max(0.0, (y1 - y0) - 2 * gap - fw)
        x = x0 + gap + fd / 2 if side == "left" else x1 - gap - fd / 2
        foot = box(x - fd / 2, y - fw / 2, x + fd / 2, y + fw / 2)
    return (x, y), foot


def _place(p, name, avoid, door_walls, label, positions=(0.5,), opposite=True):
    """The best spot for a block against a wall: inside the room, clear of `avoid` (door zones and
    furniture already placed), preferring walls without a door (and the one facing the door), then
    clear of the room's label, then centred. None if nothing fits."""
    facing = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
    best = None
    for side in ("top", "bottom", "left", "right"):
        for where in positions:
            (x, y), foot = _against(p, name, side, where)
            if not p.buffer(1e-6).contains(foot) or foot.intersection(avoid).area > 1e-4:
                continue
            score = (
                (0 if side not in door_walls else 2)
                + (0 if not opposite or not door_walls or facing[side] in door_walls else 1)
                + foot.intersection(label).area * 2
                + abs(where - 0.5) * 0.6
            )
            if best is None or score < best[0]:
                best = (score, (x, y), _WALL_ROT[side], foot)
    return best[1:] if best else None


def _furnish(msp, use, p, T, doors=(), windows=()):
    x0, y0, x1, y1 = p.bounds
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    zones = _door_zones(p, doors)
    door_walls = _door_walls(p, doors)
    # Nothing tall stands in front of a window (a kitchen counter under one is fine).
    glass = unary_union([g.buffer(0.35) for g in windows]).intersection(p) if windows else Polygon()
    blocked = zones.union(glass)
    c = p.centroid
    label = box(c.x - 0.9, c.y - 0.7, c.x + 0.9, c.y + 0.35)  # name, area and size texts

    def put(name, at, rot=0.0):
        msp.add_blockref(name, T(at), dxfattribs={"layer": "FURNITURE", "rotation": rot})

    def place(name, avoid, positions=(0.5,), opposite=True):
        spot = _place(p, name, avoid, door_walls, label, positions, opposite)
        if spot:
            put(name, spot[0], spot[1])
        return spot

    along = (0.5, 0.25, 0.75, 0.0, 1.0)
    if use == "bedroom" and w >= 2.6 and h >= 2.6:
        place("BED-D", blocked, along, opposite=False)
    elif use == "living" and w >= 2.6 and h >= 2.4:
        place("SOFA-3", zones, along, opposite=False)  # low enough to sit under a window
    elif use == "habitable" and w >= 2.6 and h >= 2.6:
        # The table (long side along the room) in the free half: clear of doors and the label.
        rot, hx, hy = (90.0, 0.9, 0.75) if h > w else (0.0, 0.75, 0.9)
        grid = [(x0 + i * 0.1, y0 + j * 0.1) for i in range(int(w * 10) + 1) for j in range(int(h * 10) + 1)]
        for x, y in sorted(grid, key=lambda q: math.hypot(q[0] - cx, q[1] - cy)):
            foot = box(x - hx - 0.15, y - hy - 0.15, x + hx + 0.15, y + hy + 0.15)
            if p.buffer(-0.1).contains(foot) and foot.intersection(zones).area < 1e-4 and foot.intersection(label).area < 1e-4:
                put("DINING-6", (x, y), rot)
                break
    elif use == "kitchen" and w >= 1.4 and h >= 1.4:
        # A 600 mm counter along the two adjacent walls without a door (or the fewest), never in front of one.
        gap = INT_T / 2 + 0.02
        strips = {
            "bottom": box(x0 + gap, y0 + gap, x1 - gap, y0 + gap + 0.6),
            "top": box(x0 + gap, y1 - gap - 0.6, x1 - gap, y1 - gap),
            "left": box(x0 + gap, y0 + gap, x0 + gap + 0.6, y1 - gap),
            "right": box(x1 - gap - 0.6, y0 + gap, x1 - gap, y1 - gap),
        }
        pairs = [("bottom", "left"), ("left", "top"), ("top", "right"), ("right", "bottom")]
        a, b = min(pairs, key=lambda s: (len(set(s) & door_walls), -sum(strips[k].difference(zones).area for k in s)))
        counter = unary_union([strips[a], strips[b]]).difference(zones.buffer(0.05))
        pieces = [g for g in getattr(counter, "geoms", [counter]) if g.geom_type == "Polygon" and g.area >= 0.72]
        for g in pieces:
            _pl(msp, [T(q) for q in _ring(g.exterior)], "FURNITURE")
        if pieces:
            # Sink and a two-burner hob on the longest run, so the counter reads as a kitchen.
            run = max(pieces, key=lambda g: g.area)
            rx0, ry0, rx1, ry1 = run.bounds
            horizontal = rx1 - rx0 >= ry1 - ry0
            length = (rx1 - rx0) if horizontal else (ry1 - ry0)

            def at(t):  # a point on the run's centre line, t metres from its start
                return (rx0 + t, (ry0 + ry1) / 2) if horizontal else ((rx0 + rx1) / 2, ry0 + t)

            sx, sy = at(min(0.5, length / 2))
            hw, hh = (0.25, 0.2) if horizontal else (0.2, 0.25)
            _pl(msp, [T(q) for q in ((sx - hw, sy - hh), (sx + hw, sy - hh), (sx + hw, sy + hh), (sx - hw, sy + hh))], "FURNITURE")
            msp.add_circle(T((sx, sy)), 0.05, dxfattribs={"layer": "FURNITURE"})
            if length >= 1.6:
                for t in (length - 0.65, length - 0.35):
                    msp.add_circle(T(at(t)), 0.11, dxfattribs={"layer": "FURNITURE"})
    elif use in ("bathroom", "wc") and w >= 0.9 and h >= 1.2:
        wc = place("WC", blocked, positions=(0.0, 1.0, 0.5))
        if wc and use == "bathroom" and w * h >= 2.5:
            place("BASIN", blocked.union(wc[2].buffer(0.15)), positions=(0.0, 1.0, 0.5), opposite=False)
    elif use == "parking" and w >= 5 and h >= 5:
        n = int((w - 1.0) // 2.5)
        for i in range(n):
            bay = box(x0 + 0.5 + i * 2.5, y1 - 5.5, x0 + 0.5 + (i + 1) * 2.5, y1 - 0.5)
            _pl(msp, [T(q) for q in _ring(bay.exterior)], "_Parking")
            put("CAR", (bay.centroid.x, bay.centroid.y))


# ---------------------------------------------------------------------------- site plan and section


def site(msp, m) -> None:
    b = m["site"]["boundary"]
    plot = Polygon(b)
    fp = Polygon(m["building"]["footprint"])
    _hatch(msp, fp, "HATCH", pattern="ANSI31", scale=0.08, color=8)
    for e in m["site"]["edges"]:
        (ax, ay), (bx, by) = e["a"], e["b"]
        ln = math.hypot(bx - ax, by - ay)
        nx, ny = (by - ay) / ln, -(bx - ax) / ln  # outward
        if e["kind"]["value"] == "road":
            w = e["road_width_m"]["value"]
            msp.add_line((ax + nx * w / 2 - (bx - ax) / ln * 6, ay + ny * w / 2 - (by - ay) / ln * 6),
                         (bx + nx * w / 2 + (bx - ax) / ln * 6, by + ny * w / 2 + (by - ay) / ln * 6),
                         dxfattribs={"layer": "CENTRELINE"})  # fmt: skip
        else:
            depth = 6.0
            adj = [(ax, ay), (bx, by), (bx + nx * depth, by + ny * depth), (ax + nx * depth, ay + ny * depth)]
            _pl(msp, adj, "ANNO")
            c = Polygon(adj).centroid
            _text(msp, "ADJOINING PLOT", (c.x, c.y), "ANNO", 0.4, rot=0 if abs(ny) > 0.5 else 90)
        # setback dimension from this side to the building
        mid = ((ax + bx) / 2, (ay + by) / 2)
        far = (mid[0] - nx * 100, mid[1] - ny * 100)
        hit = LineString([mid, far]).intersection(fp.exterior)
        pts = [hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))
        if pts:
            q = min(pts, key=lambda g: g.distance(Point(mid)))
            angle = 90 if abs(ny) > 0.5 else 0
            _dim(msp, mid, (q.x, q.y), (mid[0] + (bx - ax) / ln * 2.5, mid[1] + (by - ay) / ln * 2.5), angle=angle)
    x0, y0, x1, y1 = plot.bounds
    road_w = max((e["road_width_m"]["value"] or 0) for e in m["site"]["edges"] if e["kind"]["value"] == "road")
    frame = box(x0 - 9, y0 - road_w - 4.5, x1 + 9, y1 + 9)
    _pl(msp, _ring(frame.exterior), "_Site Plan")
    _text(msp, "SITE PLAN", ((x0 + x1) / 2, y0 - road_w - 2.6), "_Site Plan", 0.8)
    _text(msp, "SCALE 1:200", ((x0 + x1) / 2, y0 - road_w - 3.7), "TITLE", 0.35)
    msp.add_blockref("NORTH", (x1 + 5, y1 + 4.5), dxfattribs={"layer": "ANNO"})


def section(msp, levels, roof, sx0, width=12.0) -> None:
    """Slabs, outer walls, parapet, ground with earth hatch, level marks and the height dimension
    around the PreDCR _FloorInSection rectangles."""
    slab, wall = 0.15, EXT_T
    zs = [lv["elevation_m"] for lv in levels] + [roof]
    for z in zs[1:]:
        s = box(sx0 - wall, z - slab, sx0 + width + wall, z)
        _pl(msp, _ring(s.exterior), "WALL")
        _hatch(msp, s, "HATCH", color=8)
    for x in (sx0 - wall, sx0 + width):
        w = box(x, zs[0], x + wall, roof + 1.0)
        _pl(msp, _ring(w.exterior), "WALL")
        _hatch(msp, w, "HATCH", color=8)
    earth = box(sx0 - 4, -0.8, sx0 + width + 4, 0.0)
    _hatch(msp, earth, "HATCH", pattern="EARTH", scale=0.05, color=8)
    for z in zs:
        msp.add_lwpolyline([(sx0 + width + 1.0, z), (sx0 + width + 1.3, z + 0.25), (sx0 + width + 0.7, z + 0.25)],
                           close=True, dxfattribs={"layer": "ANNO"})  # fmt: skip
        _text(msp, f"{'+' if z >= 0 else ''}{z:.2f}", (sx0 + width + 1.6, z + 0.12), "ANNO", 0.25,
              align=TextEntityAlignment.MIDDLE_LEFT)  # fmt: skip
    _dim(msp, (sx0 + width + 3.6, 0.0), (sx0 + width + 3.6, roof), (sx0 + width + 4.2, 0.0), angle=90)
    frame = box(sx0 - 5, -3.0, sx0 + width + 6.5, roof + 3.0)
    _pl(msp, _ring(frame.exterior), "_Section")
    _text(msp, "SECTION A-A", (sx0 + width / 2, -1.6), "_Section", 0.6)
    _text(msp, "SCALE 1:100", (sx0 + width / 2, -2.4), "TITLE", 0.25)
