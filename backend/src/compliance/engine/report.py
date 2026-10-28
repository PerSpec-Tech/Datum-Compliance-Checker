"""Assemble a CheckReport (schemas/check-report.schema.json) from a model and the rule base.

Deterministic: no LLM. The explainer may later fill `explanation`, and the freshness stage
 may update each result's `freshness`; neither changes a status.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from compliance.engine.derived import compute
from compliance.engine.evaluate import evaluate, summarise
from compliance.engine.fsi import fsi_summary
from compliance.engine.questions import plan
from compliance.engine.rules import RuleBase


def build_report(
    model: Mapping[str, Any],
    rulebase: RuleBase,
    *,
    project_id: str,
    model_version: str,
    rulesets: list[str] | None = None,
) -> dict[str, Any]:
    """`rulesets` defaults to the model's project.rulesets fact."""
    if rulesets is None:
        rulesets = model["project"]["rulesets"]["value"]
    if not rulesets:
        raise ValueError("no rule sets: resolve the planning authority first")
    rules = rulebase.select(list(rulesets))
    derived = compute(model)
    results = evaluate(model, rules, rulebase.tables, derived)
    advisory = {r.id for r in rules if r.kind == "advisory"}
    return {
        "id": uuid.uuid4().hex,
        "project_id": project_id,
        "model_version": model_version,
        "ruleset_version": rulebase.version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summarise(results),
        "results": results,
        "questions": plan(results, advisory),
        "explanation": None,
        "fsi": fsi_summary(results, rulebase.rules, derived),
    }
