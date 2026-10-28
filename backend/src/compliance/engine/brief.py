"""Apply declared answers (the planner's questions, via PATCH /brief) over a BuildingModel.

Answers are keyed by the same paths the engine reports as missing, e.g.
  site.edges[e1].road_width_m · project.zone · project.overlays.metro_tod · spaces[S4].usage
plus one grouped form for edge tags:
  site.edges → {"e1": {"kind": "road", "road_width_m": 12,
                        "road_width_basis": "development_plan"}, …}
and the plot drawn on the map in the web app:
  site.boundary  → [[x, y], …] in model coordinates: replaces the plot; its sides become e1…en,
                   untagged, so tag them with site.edges (applied after the boundary)
  site.placement → {lat, lon, rotation_deg, scale}: where the drawing sits on the map; kept for the
                   web app only, the check doesn't use it
Declared always wins. Answers that no longer match the model (e.g. an edge that was redrawn)
are skipped and reported, never forced in.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]+)\])?")
_FACT_KEYS = {"value", "source", "note", "confidence"}


def apply_brief(
    model: Mapping[str, Any], answers: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """Return (merged copy, skipped paths). `answers` maps path → Fact ({value, source})."""
    merged = copy.deepcopy(dict(model))
    skipped: list[str] = []
    order = sorted(answers, key=lambda p: p != "site.boundary")  # new sides before their tags
    for path in order:
        fact = answers[path]
        value = fact.get("value") if isinstance(fact, Mapping) else fact
        if path == "site.placement":
            continue
        if path == "site.boundary":
            if not _set_boundary(merged, value):
                skipped.append(path)
            continue
        if path == "site.edges" and isinstance(value, Mapping):
            for edge_id, tags in value.items():
                for key in ("kind", "road_width_m", "road_width_basis"):
                    if key in tags and not _set(merged, f"site.edges[{edge_id}].{key}", tags[key]):
                        skipped.append(f"site.edges[{edge_id}].{key}")
            continue
        if not _set(merged, path, value):
            skipped.append(path)
    return merged, skipped


def _set_boundary(model: dict[str, Any], ring: Any) -> bool:
    """A plot drawn on the map replaces the model's plot and its sides."""
    try:
        pts = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in ring]
    except (TypeError, ValueError, IndexError):
        return False
    if len(pts) > 3 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return False
    note = "plot drawn on the map"
    site = model["site"]
    site["boundary"] = pts
    site["edges"] = [
        {
            "id": f"e{i + 1}",
            "a": a,
            "b": pts[(i + 1) % len(pts)],
            "kind": {"value": None, "source": "default", "note": note},
            "road_width_m": {"value": None, "source": "default", "note": None},
            "road_width_basis": {"value": None, "source": "default", "note": None},
        }
        for i, a in enumerate(pts)
    ]
    return True


def _set(model: dict[str, Any], path: str, value: Any) -> bool:
    parts = path.split(".")
    node: Any = model
    for i, part in enumerate(parts):
        m = _TOKEN.fullmatch(part)
        if m is None or not isinstance(node, dict) or m.group(1) not in node:
            return False
        last = i == len(parts) - 1
        name, element = m.group(1), m.group(2)
        if element is not None:
            items = node[name]
            match = next((e for e in items if isinstance(e, dict) and e.get("id") == element), None)
            if match is None:
                return False
            if last:
                return False  # can't replace a whole element
            node = match
            continue
        if last:
            target = node[name]
            if isinstance(target, dict) and _FACT_KEYS >= set(target) and "source" in target:
                node[name] = {"value": value, "source": "declared"}
                return True
            return False  # only facts can be declared; measured values come from the model
        node = node[name]
    return False
