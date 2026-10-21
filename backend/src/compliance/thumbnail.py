"""Axonometric thumbnail of a BuildingModel as SVG (web cards: samples, recent projects).

Each storey is the footprint extruded to the next level, drawn see-through from the front-left;
rooms whose worst result failed are red on their floor, plot sides that failed are red on the
ground. Colours are the web app's CSS tokens, so the SVG is meant to be inlined, not used as <img>.
Deterministic and model-only: no drawing vectors, no LLM.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

C, S = math.cos(math.radians(30)), math.sin(math.radians(30))
RED = "var(--danger)"


def _p(x: float, y: float, z: float) -> tuple[float, float]:
    """World (x east, y north, z up) → screen (right, down), seen from the south-west, above."""
    return (x - y) * C, -(x + y) * S - z


def _pts(ring: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in ring)


def _ring(poly: Polygon) -> list[tuple[float, float]]:
    pts = list(poly.exterior.coords)[:-1]
    return pts if poly.exterior.is_ccw else pts[::-1]


def plan_svg(model: Mapping[str, Any], status: Mapping[str, str] | None = None) -> str:
    status = status or {}
    levels = sorted(model.get("levels") or [], key=lambda lv: lv["elevation_m"])
    building = model.get("building") or {}
    site = model.get("site") or {}
    spaces = [s for s in model.get("spaces") or [] if s.get("polygon") and len(s["polygon"]) > 2]
    fp = building.get("footprint")
    roof = building.get("roof_top_m")

    def outline(level_id: str) -> Polygon | None:
        rooms = [Polygon(s["polygon"]) for s in spaces if s["level_id"] == level_id]
        rooms = [r.buffer(0) for r in rooms if r.area > 0]
        if rooms:
            u = unary_union(rooms).buffer(0.3).buffer(-0.3)
            if u.geom_type == "Polygon":
                return u
            return max(u.geoms, key=lambda g: g.area) if not u.is_empty else None
        return Polygon(fp) if fp and len(fp) > 2 else None

    parts: list[str] = []
    allpts: list[tuple[float, float]] = []

    def poly(ring3: list[tuple[float, float, float]], **attrs: Any) -> None:
        scr = [_p(*q) for q in ring3]
        allpts.extend(scr)
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        parts.append(f'<polygon points="{_pts(scr)}" vector-effect="non-scaling-stroke" {a}/>')

    def line(a3: tuple[float, float, float], b3: tuple[float, float, float], **attrs: Any) -> None:
        (x1, y1), (x2, y2) = _p(*a3), _p(*b3)
        allpts.extend([(x1, y1), (x2, y2)])
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'vector-effect="non-scaling-stroke" {a}/>'
        )

    # ground: plot and its sides
    boundary = site.get("boundary")
    if boundary and len(boundary) > 2:
        poly([(x, y, 0.0) for x, y in boundary], fill="var(--bg-surface)",
             stroke="var(--draw-fine)", stroke_width="1")  # fmt: skip
    for e in site.get("edges") or []:
        bad = status.get(e["id"]) == "fail"
        road = (e.get("kind") or {}).get("value") == "road"
        if bad or road:
            line((*e["a"], 0.0), (*e["b"], 0.0), stroke=RED if bad else "var(--draw-line)",
                 stroke_width="3" if bad else "2", stroke_linecap="round")  # fmt: skip

    for i, lv in enumerate(levels):
        z0 = float(lv["elevation_m"])
        z1 = float(levels[i + 1]["elevation_m"]) if i + 1 < len(levels) else float(roof or z0 + 3)
        if z1 <= z0:
            continue
        shape = outline(lv["id"])
        if shape is None:
            continue
        # failing rooms on this floor, under the see-through storey
        for s in spaces:
            if s["level_id"] == lv["id"] and status.get(s["id"]) == "fail":
                poly([(x, y, z0 + 0.02) for x, y in s["polygon"]], fill=RED, fill_opacity="0.9",
                     stroke=RED, stroke_width="1")  # fmt: skip
        ring = _ring(shape)
        # walls facing the viewer (outward normal towards south-west)
        for k, (ax, ay) in enumerate(ring):
            bx, by = ring[(k + 1) % len(ring)]
            nx, ny = by - ay, -(bx - ax)  # outward for a ccw ring
            if -nx - ny <= 0:
                continue
            poly([(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)],
                 fill="var(--bg-surface-raised)", fill_opacity="0.3",
                 stroke="var(--draw-line)", stroke_width="0.75")  # fmt: skip
        top = i == len(levels) - 1
        poly([(x, y, z1) for x, y in ring], fill="var(--bg-surface-raised)",
             fill_opacity="0.85" if top else "0.25", stroke="var(--text-primary)",
             stroke_width="1.25" if top else "0.75", stroke_linejoin="round")  # fmt: skip
        if top:  # the top floor's rooms drawn on its roof, for a sense of the plan
            for sp in spaces:
                if sp["level_id"] == lv["id"]:
                    poly([(x, y, z1) for x, y in sp["polygon"]], fill="none",
                         stroke="var(--draw-line)", stroke_width="0.5")  # fmt: skip

    if not allpts:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 3"></svg>'
    xs, ys = [p[0] for p in allpts], [p[1] for p in allpts]
    pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.06
    vb = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(f"{v:.2f}" for v in vb)}" '
        'preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>"
    )


def worst_by_element(report: Mapping[str, Any] | None) -> dict[str, str]:
    rank = {"fail": 0, "unverifiable": 1, "advisory": 2, "pass": 3}
    out: dict[str, str] = {}
    for r in (report or {}).get("results", []):
        el, st = r.get("element") or {}, r["status"]
        if not el.get("id") or st not in rank:
            continue
        if el["id"] not in out or rank[st] < rank[out[el["id"]]]:
            out[el["id"]] = st
    return out


# ---------------------------------------------------------------------- the file itself
# Card thumbnails show what is in the file: a 2D drawing's ground-floor plan, an IFC's building in
# 3D. The axonometric sketch above is only the fallback (a model sent from Revit has neither).

_DRAW_ORDER = ("room", "furniture", "dim", "stair", "window", "door", "wall")
_DRAW_STYLE = {
    "wall": ("var(--draw-wall)", 1.4),
    "door": ("var(--draw-line)", 0.7),
    "window": ("var(--draw-line)", 0.7),
    "stair": ("var(--draw-line)", 0.7),
    "furniture": ("var(--draw-fine)", 0.5),
    "dim": ("var(--draw-fine)", 0.4),
    "room": ("var(--draw-fine)", 0.4),
}


def floor_svg(drawing: Mapping[str, Any]) -> str | None:
    """The ground-floor plan of a 2D drawing (GET /projects/{id}/drawing data) as SVG."""
    floors = drawing.get("floors") or []
    if not floors:
        return None
    floor = next((f for f in floors if 0 in f["nums"]), None) or min(
        floors, key=lambda f: min(f["nums"] or [0])
    )
    lines = [(c, line) for c in _DRAW_ORDER for line in floor["paths"].get(c, [])]
    pts = [v for _, line in lines for v in line] + [v for f in floor["fills"] for v in f]
    if not pts:
        return None
    xs, ys = pts[0::2], pts[1::2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = max(x1 - x0, y1 - y0) * 0.05

    def d(flat: list[float], close: bool = False) -> str:
        out = "".join(
            f"{'L' if i else 'M'}{flat[i] - x0 + pad:.2f} {y1 - flat[i + 1] + pad:.2f}"
            for i in range(0, len(flat) - 1, 2)
        )
        return out + ("Z" if close else "")

    parts = [
        f'<path d="{"".join(d(f, True) for f in floor["fills"])}" fill="var(--draw-wall)" '
        'fill-rule="evenodd"/>'
    ]
    for c in _DRAW_ORDER:
        group = [line for k, line in lines if k == c]
        if group:
            colour, width = _DRAW_STYLE[c]
            parts.append(
                f'<path d="{"".join(d(g) for g in group)}" fill="none" stroke="{colour}" '
                f'stroke-width="{width}" stroke-linejoin="round" '
                'vector-effect="non-scaling-stroke"/>'
            )
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" '
        f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>'
    )


# Neutral mid-tones that read on both the dark and the light theme.
_MESH_COLOUR = {
    "IfcWall": (0.86, 0.86, 0.87),
    "IfcWallStandardCase": (0.86, 0.86, 0.87),
    "IfcSlab": (0.74, 0.74, 0.76),
    "IfcRoof": (0.70, 0.70, 0.72),
    "IfcWindow": (0.45, 0.50, 0.55),
    "IfcDoor": (0.55, 0.55, 0.58),
    "IfcStairFlight": (0.66, 0.66, 0.68),
    "IfcSite": (0.32, 0.32, 0.34),
}
_CONTEXT_COLOUR = (0.42, 0.42, 0.45)
_SKIP = {"IfcSpace", "IfcOpeningElement"}


def mesh_png(mesh: Mapping[str, Any], width: int = 480, height: int = 340, ss: int = 2) -> bytes:
    """IFC geometry (adapters.mesh output) seen from the south-west, as a small PNG: a z-buffer
    rasteriser with flat shading and edge lines, written with numpy and zlib only."""
    import numpy as np

    tris, cols, keys, behind = [], [], [], []
    groups = ((mesh.get("elements") or [], False), (mesh.get("context") or [], True))
    for group, is_context in groups:
        for k, el in enumerate(group):
            if el["type"] in _SKIP:
                continue
            v = np.asarray(el["v"], dtype=np.float64).reshape(-1, 3)
            f = np.asarray(el["f"], dtype=np.int64).reshape(-1, 3)
            if not len(f) or (is_context and np.ptp(v[:, 2]) > 0.5):
                continue  # neighbouring buildings would hide this one: keep plot and roads
            tris.append(v[f])
            neutral = _MESH_COLOUR.get(el["type"], (0.78, 0.78, 0.8))
            c = _CONTEXT_COLOUR if is_context and el["type"] != "IfcSite" else neutral
            cols.append(np.tile(c, (len(f), 1)))
            behind.append(np.full(len(f), 0.25 if is_context else 0.0))  # ground under slabs
            site = el["type"] == "IfcSite"
            keys.append(np.full(len(f), (1 if site or not is_context else 2) * 100_000 + k))
    W, H = width * ss, height * ss
    if not tris:
        return _png(np.zeros((height, width, 4), dtype=np.uint8))
    T = np.concatenate(tris)  # (n triangles, 3 vertices, xyz)
    colour = np.concatenate(cols)
    element = np.concatenate(keys)

    fwd = np.array([1.0, 1.0, -0.85]) / np.linalg.norm([1.0, 1.0, -0.85])  # looking NE, down
    right = np.array([1.0, -1.0, 0.0]) / np.sqrt(2)
    up = np.cross(right, fwd)
    sx, sy, sz = T @ right, T @ up, T @ fwd
    sz = sz + np.concatenate(behind)[:, None]
    # frame the building, not the whole neighbourhood
    own = element < 200_000
    fx, fy = (sx[own], sy[own]) if own.any() else (sx, sy)
    lo_x, hi_x, lo_y, hi_y = fx.min(), fx.max(), fy.min(), fy.max()
    scale = min(W * 0.86 / max(hi_x - lo_x, 1e-6), H * 0.86 / max(hi_y - lo_y, 1e-6))
    px = (sx - (lo_x + hi_x) / 2) * scale + W / 2
    py = H / 2 - (sy - (lo_y + hi_y) / 2) * scale

    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.45, -0.7, 0.55]) / np.linalg.norm([-0.45, -0.7, 0.55])
    shade = 0.5 + 0.5 * np.abs(n @ light)  # two-sided: IFC windings vary
    rgb = np.clip(colour * shade[:, None], 0, 1)
    # same element and same plane → one face, so coplanar triangles draw no seam
    plane = np.round(np.abs(n) @ np.array([7.0, 131.0, 2027.0]) * 4).astype(np.int64)
    face = element * 1_000_003 + plane

    zbuf = np.full((H, W), np.inf)
    ids = np.full((H, W), -1, dtype=np.int64)
    for i in range(len(T)):
        xs, ys, zs = px[i], py[i], sz[i]
        x0, x1 = max(int(xs.min()), 0), min(int(xs.max()) + 1, W - 1)
        y0, y1 = max(int(ys.min()), 0), min(int(ys.max()) + 1, H - 1)
        if x0 > x1 or y0 > y1:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, bx, cx), (ay, by, cy) = xs, ys
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        depth = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        zb, ib = zbuf[y0 : y1 + 1, x0 : x1 + 1], ids[y0 : y1 + 1, x0 : x1 + 1]
        win = inside & (depth < zb)
        zb[win] = depth[win]
        ib[win] = i

    hit = ids >= 0
    img = np.zeros((H, W, 4))
    img[hit, :3] = rgb[ids[hit]]
    img[hit, 3] = 1.0
    # edge lines where the visible face changes
    fid = np.where(hit, face[np.maximum(ids, 0)], -1)
    edge = np.zeros((H, W), dtype=bool)
    edge[:, 1:] |= fid[:, 1:] != fid[:, :-1]
    edge[1:, :] |= fid[1:, :] != fid[:-1, :]
    img[edge & hit, :3] *= 0.35
    outline = edge & ~hit
    img[outline, :3] = 0.2
    img[outline, 3] = 0.6
    # downsample: anti-aliasing
    img = img.reshape(height, ss, width, ss, 4)
    alpha = img[..., 3].mean(axis=(1, 3))
    rgb_sum = (img[..., :3] * img[..., 3:]).sum(axis=(1, 3))
    weight = img[..., 3].sum(axis=(1, 3))[..., None]
    rgb_out = np.where(weight > 0, rgb_sum / np.maximum(weight, 1e-9), 0)
    out = np.concatenate([rgb_out, alpha[..., None]], axis=2)
    return _png((np.clip(out, 0, 1) * 255).round().astype(np.uint8))


def _png(rgba: Any) -> bytes:
    """Minimal RGBA PNG encoder (stdlib zlib)."""
    import struct
    import zlib

    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
