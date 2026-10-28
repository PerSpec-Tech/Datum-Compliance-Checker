"""Live pack: the rule engine's limits for one project, as geometry and numbers the
Revit / AutoCAD add-ins can test locally while the user models. Deterministic, no LLM.

Everything here comes from an evaluated check: margins and their clause refs from the margin
rules' own limits per plot side; the FSI budget from the FSI summary; per-element thresholds from
rules whose measure is a plain element field and whose limit is a constant for this project.
Margins can depend on building height (UDCPR: H/5 above some heights), so each side carries a
table of its margin by height; the add-in reads it at the live height as the model grows.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from shapely.geometry import Polygon

from compliance.engine.derived import Derived, compute
from compliance.engine.evaluate import evaluate
from compliance.engine.rules import RuleBase

_FIELD = re.compile(r"^\s*item\.([a-z_]+)\s*$")
_OP = re.compile(r"^\s*measured\s*(>=|<=|>|<)\s*limit\s*$")
_RUN = ("pass", "fail", "unverifiable")
STEP_M, MAX_M = 0.1, 70.0


def build_live_pack(
    model: Mapping[str, Any], rulebase: RuleBase, report: Mapping[str, Any]
) -> dict[str, Any]:
    rules = rulebase.select(list(model["project"]["rulesets"]["value"] or []))
    derived = compute(model)
    notes: list[str] = []

    edges = _edge_margins(model, report)
    envelope = _envelope(model, edges)
    if envelope is None and edges:
        notes.append("Some plot sides have no known margin yet: answer the brief, then re-check.")
    _margin_tables(model, rules, rulebase, derived, edges)
    limit = _height_limit(model, rules, rulebase, derived)

    fsi = report.get("fsi") or {}
    plot = fsi.get("plot_area_m2")

    def area(x: float | None) -> float | None:
        return round(x * plot, 2) if x is not None and plot is not None else None

    return {
        "project_id": report["project_id"],
        "model_version": report["model_version"],
        "report_id": report["id"],
        "ruleset_version": report["ruleset_version"],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "edges": edges,
        "envelope": envelope,
        "fsi": {
            "plot_area_m2": plot,
            "base": fsi.get("base_permissible"),
            "max": fsi.get("max_permissible"),
            "base_built_up_m2": area(fsi.get("base_permissible")),
            "max_built_up_m2": area(fsi.get("max_permissible")),
            "used_m2": fsi.get("built_up_m2"),
            "rule_ids": list(fsi.get("rule_ids") or []),
        },
        "height": {
            "current_m": derived.values.get("building_height_m"),
            "step_m": STEP_M,
            "max_m": MAX_M,
            **limit,
        },
        "thresholds": _thresholds(report, rulebase),
        "notes": notes,
    }


def _edge_margins(model: Mapping[str, Any], report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per plot side: the largest margin any applicable rule requires, with its clause."""
    by_edge: dict[str, list[Mapping[str, Any]]] = {}
    for r in report["results"]:
        el = r.get("element") or {}
        if el.get("kind") == "site.edges" and r["status"] in _RUN:
            by_edge.setdefault(el["id"], []).append(r)
    out = []
    for e in model["site"]["edges"]:
        rs = by_edge.get(e["id"], [])
        known = [
            r for r in rs if isinstance(r["limit"], (int, float)) and r["status"] != "unverifiable"
        ]
        best = max(known, key=lambda r: r["limit"], default=None)
        unknown = any(r["status"] == "unverifiable" for r in rs)
        out.append({
            "edge_id": e["id"], "a": e["a"], "b": e["b"], "kind": e["kind"]["value"],
            "margin_m": float(best["limit"]) if best and not unknown else None,
            "rule_id": best["rule_id"] if best else None,
            "clause_ref": best["clause"]["ref"] if best else None,
            "margin_by_height": [],
        })  # fmt: skip
    return out


def _envelope(model: Mapping[str, Any], edges: list[dict[str, Any]]) -> list[list[float]] | None:
    """The plot inset by each side's margin (intersection of inward half-planes)."""
    boundary = model["site"]["boundary"]
    if not boundary or not edges or any(e["margin_m"] is None for e in edges):
        return None
    shape = Polygon(boundary)
    ccw = shape.exterior.is_ccw
    big = 1e4
    for e in edges:
        (ax, ay), (bx, by) = e["a"], e["b"]
        ln = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
        ux, uy = (bx - ax) / ln, (by - ay) / ln
        nx, ny = (-uy, ux) if ccw else (uy, -ux)  # inward normal
        m = e["margin_m"]
        p0 = (ax + nx * m - ux * big, ay + ny * m - uy * big)
        p1 = (bx + nx * m + ux * big, by + ny * m + uy * big)
        half = Polygon(
            [p0, p1, (p1[0] + nx * big, p1[1] + ny * big), (p0[0] + nx * big, p0[1] + ny * big)]
        )
        shape = shape.intersection(half)
        if shape.is_empty:
            return None
    if shape.geom_type != "Polygon":
        shape = max(getattr(shape, "geoms", []), key=lambda g: g.area, default=None)
        if shape is None:
            return None
    return [[round(x, 4), round(y, 4)] for x, y in list(shape.exterior.coords)[:-1]]


def _margin_tables(
    model: Mapping[str, Any],
    rules: list[Any],
    rulebase: RuleBase,
    derived: Derived,
    edges: list[dict[str, Any]],
) -> None:
    """Fill each side's margin_by_height by re-evaluating the margin rules at sampled heights."""
    edge_rules = [r for r in rules if r.for_each == "site.edges"]
    if not edge_rules or not edges or any(e["margin_m"] is None for e in edges):
        return
    samples = [round(i * STEP_M, 2) for i in range(int(MAX_M / STEP_M) + 1)]
    table: dict[str, list[float | None]] = {e["edge_id"]: [] for e in edges}
    for h in samples:
        d = dataclasses.replace(derived, values={**derived.values, "building_height_m": h})
        at: dict[str, float] = {}
        for r in evaluate(model, edge_rules, rulebase.tables, d):
            el = r.get("element") or {}
            if el.get("kind") == "site.edges" and r["status"] in ("pass", "fail"):
                if isinstance(r["limit"], (int, float)):
                    at[el["id"]] = max(at.get(el["id"], 0.0), float(r["limit"]))
        for k in table:
            table[k].append(round(at[k], 4) if k in at else None)
    for e in edges:
        col = table[e["edge_id"]]
        e["margin_by_height"] = [] if len(set(col)) == 1 else col  # constant: no table needed


def _height_limit(
    model: Mapping[str, Any], rules: list[Any], rulebase: RuleBase, derived: Derived
) -> dict[str, Any]:
    """The tallest the building may be: the first sampled height a building-height rule fails,
    less one step (the road-width rule: over 36 m needs a 12 m road). None if nothing limits it."""
    none = {"limit_m": None, "limit_rule_id": None, "limit_clause_ref": None}
    tall = [r for r in rules if r.for_each is None and "building_height_m" in str(r.doc)]
    if not tall:
        return none
    prev = 0.0
    for i in range(int(MAX_M / STEP_M) + 1):
        h = round(i * STEP_M, 2)
        d = dataclasses.replace(derived, values={**derived.values, "building_height_m": h})
        failed = [r for r in evaluate(model, tall, rulebase.tables, d) if r["status"] == "fail"]
        if failed:
            if h == 0:
                return none  # fails whatever the height: not a height limit
            return {
                "limit_m": prev,
                "limit_rule_id": failed[0]["rule_id"],
                "limit_clause_ref": failed[0]["clause"]["ref"],
            }
        prev = h
    return none


def _thresholds(report: Mapping[str, Any], rulebase: RuleBase) -> list[dict[str, Any]]:
    """Rules like 'item.clear_height_m >= 2.75': which elements they apply to, at what limit."""
    groups: dict[tuple[str, float], dict[str, Any]] = {}
    for r in report["results"]:
        el = r.get("element") or {}
        kind = el.get("kind")
        if kind not in ("spaces", "doors", "stairs", "units") or r["status"] not in _RUN:
            continue
        if not isinstance(r["limit"], (int, float)) or isinstance(r["limit"], bool):
            continue
        doc = rulebase.rules[r["rule_id"]].doc
        f, op = _FIELD.match(doc.get("measured") or ""), _OP.match(doc.get("check") or "")
        if not f or not op:
            continue
        key = (r["rule_id"], float(r["limit"]))
        g = groups.setdefault(key, {
            "rule_id": r["rule_id"], "title": r["title"], "clause_ref": r["clause"]["ref"],
            "for_each": kind, "field": f.group(1), "op": op.group(1), "limit": float(r["limit"]),
            "element_ids": [], "source_ids": [],
        })  # fmt: skip
        g["element_ids"].append(el["id"])
        g["source_ids"].append(el.get("source_id"))
    return sorted(groups.values(), key=lambda g: (g["rule_id"], g["limit"]))
