"""FSI headroom summary: how much FSI is used, what's permitted, and what's left in m².

Built only from evaluated results of rules tagged with `metric` — the permitted values come from
the rules' own table limits, never from constants here. Numbers are None when inputs are missing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compliance.engine.derived import Derived
from compliance.engine.rules import LoadedRule

_APPLICABLE = ("pass", "fail", "advisory", "not_applicable")


def fsi_summary(
    results: list[Mapping[str, Any]], rules: Mapping[str, LoadedRule], derived: Derived
) -> dict[str, Any] | None:
    tagged = [
        r for r in results if rules[r["rule_id"]].doc.get("metric") in ("fsi_base", "fsi_max")
    ]
    if not tagged:
        return None

    v = derived.values
    plot = v["plot_area_m2"]["value"]
    used = v["far"]
    missing: list[str] = []

    def limits(metric: str) -> list[tuple[float, Mapping[str, Any]]]:
        out = []
        for r in tagged:
            if rules[r["rule_id"]].doc.get("metric") != metric:
                continue
            if r["status"] == "unverifiable":
                missing.extend(p for p in r["missing_inputs"] if p not in missing)
            elif r["status"] in _APPLICABLE and isinstance(r["limit"], (int, float)):
                # An advisory/check that ran its limit is applicable even if it didn't trigger.
                applies = r["status"] != "not_applicable" or metric == "fsi_base"
                if applies:
                    out.append((float(r["limit"]), r))
        return out

    base = limits("fsi_base")
    maxes = limits("fsi_max")
    base_value = min(base, key=lambda x: x[0]) if base else None
    max_value = max(maxes, key=lambda x: x[0]) if maxes else None

    if used is None:
        missing.extend(p for p in derived.inputs_for("derived.far") if p not in missing)

    def headroom(limit: tuple[float, Any] | None) -> float | None:
        if limit is None or used is None or plot is None:
            return None
        return round((limit[0] - used) * plot, 2)

    basis = []
    for label, item in (("Basic FSI", base_value), ("Maximum FSI", max_value)):
        if item is not None:
            limit, r = item
            basis.append(f"{label} {limit:.2f}: {r['title']} ({r['clause']['ref']})")
    road = v["front_road_width_m"]
    if road is not None:
        basis.append(f"Front road width {road:g} m")

    return {
        "plot_area_m2": plot,
        "built_up_m2": v["built_up_m2"],
        "used": used,
        "base_permissible": base_value[0] if base_value else None,
        "max_permissible": max_value[0] if max_value else None,
        "basis": basis,
        "headroom_base_m2": headroom(base_value),
        "headroom_max_m2": headroom(max_value),
        "rule_ids": sorted({r["rule_id"] for r in tagged}),
        "missing_inputs": missing,
    }
