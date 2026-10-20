"""Rule evaluator (P2.4, ROADMAP §5.4). The ONLY place a pass or fail is decided (D2).

For each rule (and each element, for `for_each` rules):
  applies_when → False: not_applicable · missing: unverifiable
  limit / measured → evaluated first, then available to `check` by name
  check → True: pass (advisory rules: advisory) · False: fail (advisory: not_applicable)
          missing: unverifiable, naming the inputs needed
Bad data never raises: an expression error becomes an unverifiable result that says why.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from compliance.engine.derived import Derived, compute
from compliance.engine.expr import EvalResult, ExprError
from compliance.engine.rules import LoadedRule

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
STATUSES = ("pass", "fail", "unverifiable", "not_applicable", "advisory")
# Collections that can never really be empty; if they are, the rule can't be verified.
ALWAYS_PRESENT = {"site.edges": ["site.boundary", "site.edges"]}
# `measured OP limit` → which way the measured value must move to pass
_FIX_DIRECTION = {
    ("measured", ast.GtE): "increase",
    ("measured", ast.Gt): "increase",
    ("measured", ast.LtE): "decrease",
    ("measured", ast.Lt): "decrease",
    ("limit", ast.LtE): "increase",  # limit <= measured
    ("limit", ast.Lt): "increase",
    ("limit", ast.GtE): "decrease",  # limit >= measured
    ("limit", ast.Gt): "decrease",
}


def evaluate(
    model: Mapping[str, Any],
    rules: list[LoadedRule],
    tables: Mapping[str, Mapping[str, Any]],
    derived: Derived | None = None,
) -> list[dict[str, Any]]:
    derived = derived or compute(model)
    ctx = {
        "project": model["project"],
        "site": model["site"],
        "building": model["building"],
        "levels": model["levels"],
        "spaces": model["spaces"],
        "areas": model["areas"],
        "stairs": model["stairs"],
        "doors": model["doors"],
        "units": model["units"],
        "derived": derived.values,
    }
    results: list[dict[str, Any]] = []
    for rule in rules:
        if rule.for_each is None:
            results.append(_evaluate_one(rule, ctx, tables, None, None, derived))
            continue
        elements = _collection(model, rule.for_each)
        if not elements and rule.for_each in ALWAYS_PRESENT:
            # Every plot has edges: an empty list means the site wasn't modelled, not "no edges".
            results.append(_unknown_collection(rule, ALWAYS_PRESENT[rule.for_each]))
            continue
        for el in elements:
            label = f"{rule.for_each}[{el['id']}]"
            element = {"kind": rule.for_each, "id": el["id"], "source_id": el.get("source_id")}
            results.append(
                _evaluate_one(rule, {**ctx, "item": el}, tables, label, element, derived)
            )
    results.sort(
        key=lambda r: (
            SEVERITY_ORDER[r["severity"]],
            r["rule_id"],
            (r["element"] or {}).get("id", ""),
        )
    )
    return results


def summarise(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for r in results:
        counts[r["status"]] += 1
    return counts


# --------------------------------------------------------------------------- one evaluation


def _collection(model: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    if name == "site.edges":
        return list(model["site"].get("edges") or [])
    return list(model.get(name) or [])


def _evaluate_one(rule, ctx, tables, label, element, derived: Derived) -> dict[str, Any]:
    labels = {"item": label} if label else {}
    reads: list[EvalResult] = []

    def run(name: str, extra: Mapping[str, Any] | None = None) -> EvalResult:
        r = rule.exprs[name].eval({**ctx, **(extra or {})}, tables=tables, labels=labels)
        reads.append(r)
        return r

    base = _result_shell(rule, element)

    def finish(status: str, **kw: Any) -> dict[str, Any]:
        out = _finish(base, status, reads, template=rule.doc["message"], derived=derived, **kw)
        _add_derived_facts(out, reads, derived)
        return out

    try:
        if "applies_when" in rule.exprs:
            applies = run("applies_when")
            if applies.is_missing:
                return finish("unverifiable", missing=applies.missing)
            if not _as_bool(applies.value, "applies_when"):
                return finish("not_applicable")

        named: dict[str, Any] = {}
        missing: set[str] = set()
        for name in ("limit", "measured"):
            if name in rule.exprs:
                r = run(name)
                if r.is_missing:
                    missing |= r.missing
                else:
                    named[name] = r.value
        base["limit"], base["measured"] = (
            _scalar(named.get("limit")),
            _scalar(named.get("measured")),
        )

        check_roots = {p.split(".", 1)[0] for p in rule.exprs["check"].paths}
        needed_missing = {n for n in ("limit", "measured") if n in check_roots and n not in named}
        if needed_missing:
            return finish("unverifiable", missing=missing)

        check = run("check", named)
        if check.is_missing:
            return finish("unverifiable", missing=check.missing)
        ok = _as_bool(check.value, "check")
    except ExprError as e:
        return finish("unverifiable", error=str(e))

    if rule.kind == "advisory":
        return finish("advisory" if ok else "not_applicable", named=named)
    status = "pass" if ok else "fail"
    out = finish(status, named=named)
    if status == "fail":
        out["fix_by"] = _fix_by(rule, named)
    return out


def _unknown_collection(rule: LoadedRule, inputs: list[str]) -> dict[str, Any]:
    out = _result_shell(rule, None)
    out["missing_inputs"] = list(inputs)
    out["message"] = "Cannot verify: needs " + ", ".join(inputs)
    return out


def _result_shell(rule: LoadedRule, element) -> dict[str, Any]:
    doc = rule.doc
    return {
        "rule_id": rule.id,
        "title": doc["title"],
        "severity": doc["severity"],
        "element": element,
        "status": "unverifiable",
        "measured": None,
        "limit": None,
        "message": "",
        "missing_inputs": [],
        "facts_used": [],
        "clause": doc["clause"],
        "rule_status": doc["status"],
        "freshness": doc.get("freshness") or {"status": "unchecked", "url": None, "checked": None},
        "fix_by": None,
        "guidance_note": doc.get("guidance_note"),
    }


def _finish(
    base, status, reads, *, template, derived, missing=frozenset(), error=None, named=None
) -> dict[str, Any]:
    base["status"] = status
    facts: dict[str, dict[str, Any]] = {}
    for r in reads:
        for f in r.facts:
            facts.setdefault(f.path, {"path": f.path, "value": f.value, "source": f.source})
    base["facts_used"] = list(facts.values())
    inputs: list[str] = []
    for p in sorted(missing):
        for q in derived.inputs_for(p):
            if q not in inputs:
                inputs.append(q)
    base["missing_inputs"] = inputs
    base["message"] = _message(base, status, error, named or {}, template)
    return base


def _message(base, status, error, named, template) -> str:
    if error:
        return f"Could not evaluate this rule: {error}"
    if status == "unverifiable":
        return "Cannot verify: needs " + ", ".join(base["missing_inputs"] or ["more information"])
    if status == "not_applicable":
        return "Not applicable to this project."
    try:
        return template.format(**named)
    except (KeyError, ValueError, TypeError, IndexError):
        return base["title"]


def _add_derived_facts(out: dict[str, Any], reads: list[EvalResult], derived: Derived) -> None:
    """Append the facts behind any derived value the rule read (e.g. the declared road width)."""
    seen = {f["path"] for f in out["facts_used"]}
    names = sorted(
        {
            p.split(".")[1].split("[")[0]
            for r in reads
            for p in r.accessed
            if p.startswith("derived.")
        }
    )
    for name in names:
        for f in derived.facts.get(name, []):
            if f["path"] not in seen:
                out["facts_used"].append(dict(f))
                seen.add(f["path"])


def _as_bool(v: Any, what: str) -> bool:
    if not isinstance(v, bool):
        raise ExprError(f"{what} must be true or false, got {type(v).__name__} {v!r}")
    return v


def _scalar(v: Any) -> Any:
    return v if isinstance(v, (int, float, str, bool)) or v is None else None


def _fix_by(rule: LoadedRule, named: Mapping[str, Any]) -> dict[str, Any] | None:
    """Only for checks shaped exactly `measured OP limit` or `limit OP measured`, with numbers."""
    node = rule.exprs["check"].tree.body
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
        return None
    left, right = node.left, node.comparators[0]
    if not (isinstance(left, ast.Name) and isinstance(right, ast.Name)):
        return None
    if {left.id, right.id} != {"measured", "limit"}:
        return None
    direction = _FIX_DIRECTION.get((left.id, type(node.ops[0])))
    m, lim = named.get("measured"), named.get("limit")
    numeric = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (m, lim))
    if direction is None or not numeric:
        return None
    return {
        "amount": round(abs(lim - m), 2),
        "unit": rule.doc.get("fix_unit"),
        "direction": direction,
    }
