"""Question planner (P2.5). Deterministic, no LLM.

Collects the missing inputs behind every 'unverifiable' result, groups them into questions, and
ranks them by how many rules each answer would unlock. Wording here is a plain template; the
`fast` model may rephrase it later (P3.9) but never changes which questions are asked.
Advisory rules never create questions (D23).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from compliance.schemas import registry

_COLLECTIONS = ("spaces", "areas", "stairs", "doors", "levels", "units")
_ID = re.compile(r"\[[^\]]*\]")


def _enum(name: str) -> list[str]:
    return list(registry().contents("common.schema.json")["definitions"][name]["enum"])


# question key → (input_type, prompt, options)
_SPECS: dict[str, tuple[str, str, list[str] | None]] = {
    "site.edges": (
        "edge_tags",
        "Which sides of the plot face a road, and how wide is each road "
        "(as per the Development Plan)?",
        None,
    ),
    "site.boundary": (
        "text",
        "The plot boundary is missing. Add property lines in Revit (or a site in the IFC).",
        None,
    ),
    "site.plot_area_declared_m2": (
        "number",
        "Plot area as per the ownership documents (sq.m)?",
        None,
    ),
    "site.is_corner_plot": ("bool", "Is this a corner plot?", None),
    "site.ground_level_m": ("number", "Average ground level of the plot (m, project datum)?", None),
    "project.location": ("latlon", "Where is the site? Drop a pin on the map.", None),
    "project.zone": (
        "text",
        "What is the Development Plan zone of the plot (e.g. residential)?",
        None,
    ),
    "project.congested_area": (
        "bool",
        "Is the plot in a congested area / Gaothan as shown in the Development Plan?",
        None,
    ),
    "project.occupancy": ("enum", "What is the building's occupancy group (NBC Part 4)?", None),
    "project.building_type": ("enum", "What type of building is this?", None),
    "project.overlays.metro_tod": (
        "bool",
        "Is the plot inside the notified metro TOD zone (500 m around a metro station)?",
        None,
    ),
    "project.overlays.plot_share_in_tod": (
        "number",
        "What share of the plot lies inside the TOD zone (0–1)?",
        None,
    ),
}
_OPTIONS = {"project.occupancy": "OccupancyGroup", "project.building_type": "BuildingType"}
# Per-element model gaps that have a natural question (count of elements is appended).
_COLLECTION_SPECS: dict[str, tuple[str, str, str | None]] = {
    "areas[*].counts_to_far": (
        "bool",
        "Do these Revit area schemes count towards FSI (built-up area)?",
        None,
    ),
    "spaces[*].usage": (
        "enum",
        "What are these rooms used for? Their names weren't recognised.",
        "Usage",
    ),
    "units[*].use": ("enum", "Are these units residential, commercial or office?", "UnitUse"),
}


def question_key(path: str) -> str | None:
    """Group a missing input path into the question that would answer it (None = not askable)."""
    if path.startswith("table:"):
        return None  # a gap in a rule table, not something the user can answer
    if path.startswith("site.edges"):
        return "site.edges"
    for prefix in ("project.occupancy", "project.location"):
        if path.startswith(prefix):
            return prefix
    head = path.split("[", 1)[0].split(".", 1)[0]
    if head in _COLLECTIONS and "[" in path:
        return _ID.sub("[*]", path)
    return path


def plan(
    results: Iterable[Mapping[str, Any]], advisory_rule_ids: Iterable[str] = ()
) -> list[dict[str, Any]]:
    skip = set(advisory_rule_ids)
    rules_by_key: dict[str, set[str]] = {}
    elements_by_key: dict[str, set[str]] = {}
    for r in results:
        if r["status"] != "unverifiable" or r["rule_id"] in skip:
            continue
        for path in r["missing_inputs"]:
            key = question_key(path)
            if key is None:
                continue
            rules_by_key.setdefault(key, set()).add(r["rule_id"])
            m = re.match(r"^\w+\[([^\]]+)\]", path)
            if m and key.split("[", 1)[0] in _COLLECTIONS:
                elements_by_key.setdefault(key, set()).add(m.group(1))

    questions = [
        _question(key, rule_ids, elements_by_key.get(key, set()))
        for key, rule_ids in rules_by_key.items()
    ]
    questions.sort(key=lambda q: (-q["unlocks"], q["path"]))
    return questions


def _question(key: str, rule_ids: set[str], elements: set[str]) -> dict[str, Any]:
    if key in _SPECS:
        input_type, prompt, options = _SPECS[key]
        if key in _OPTIONS:
            options = _enum(_OPTIONS[key])
    elif key.startswith("project.special."):
        flag = key.rsplit(".", 1)[1].replace("_", " ")
        input_type, prompt, options = "bool", f"Does this apply to the site: {flag}?", None
    elif key in _COLLECTION_SPECS:
        input_type, prompt, enum_name = _COLLECTION_SPECS[key]
        n = len(elements)
        prompt = (
            f"{prompt} ({n} {'item' if n == 1 else 'items'}: {', '.join(sorted(elements)[:6])})"
        )
        options = _enum(enum_name) if enum_name else None
    elif key.split("[", 1)[0] in _COLLECTIONS:
        coll, field = key.split("[*].", 1) if "[*]." in key else (key.split("[", 1)[0], "data")
        n = len(elements)
        prompt = f"{n} {coll if n != 1 else coll.rstrip('s')} {'have' if n != 1 else 'has'} no "
        prompt += f"'{field}' in the model. Add it in Revit/IFC and re-export."
        input_type, options = "text", None
    else:
        input_type, prompt, options = "text", f"Please provide: {key}", None
    return {
        "path": key,
        "prompt": prompt,
        "unlocks": len(rule_ids),
        "rule_ids": sorted(rule_ids),
        "input_type": input_type,
        "options": options,
    }
