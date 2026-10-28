# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, RootModel

from . import common_schema


class Expression(RootModel[str]):
    root: str = Field(..., min_length=1)


class RuleStatus(StrEnum):
    draft = "draft"
    verified = "verified"


class Severity(StrEnum):
    critical = "critical"
    major = "major"
    minor = "minor"


class RuleKind(StrEnum):
    check = "check"
    advisory = "advisory"


class Collection(StrEnum):
    spaces = "spaces"
    areas = "areas"
    stairs = "stairs"
    doors = "doors"
    levels = "levels"
    units = "units"
    site_edges = "site.edges"


class Metric(StrEnum):
    fsi_used = "fsi_used"
    fsi_base = "fsi_base"
    fsi_max = "fsi_max"


class GuidanceNote(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    text: str
    source: str = Field(..., description="Manifest doc id + page.")


class Rule(BaseModel):
    """
    One compliance rule, stored as one YAML file under rules/<ruleset>/. Expressions are Python-syntax strings evaluated only by engine/expr.py (AST whitelist, never eval/exec).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="<authority>.<part>.<slug>, unique across all rule sets.",
        pattern="^[a-z0-9_]+(\\.[a-z0-9_-]+)+$",
    )
    title: str = Field(..., min_length=3)
    authority: str = Field(
        ...,
        description="Rule set this rule belongs to, e.g. nbc2016 | udcpr2020 | pmc.",
        pattern="^[a-z0-9_]+$",
    )
    overrides: str | None = Field(
        None,
        description="Rule id from an earlier rule set that this rule replaces for projects using both sets.",
    )
    clause: common_schema.Clause
    status: RuleStatus = Field(..., description="Only a human sets 'verified'.")
    severity: Severity
    kind: RuleKind | None = Field(
        "check",
        description="'check' produces pass/fail; 'advisory' produces an obligation the model can't confirm.",
    )
    for_each: Collection | None = Field(
        None,
        description="Evaluate once per element of this collection; the element is available as `item`.",
    )
    applies_when: Expression | None = Field(
        None, description="Optional; default True. False → not_applicable."
    )
    limit: Expression | None = Field(
        None, description="Optional named expression, available to `check` as `limit`."
    )
    measured: Expression | None = Field(
        None,
        description="Optional named expression, available to `check` as `measured`.",
    )
    check: Expression = Field(
        ...,
        description="Must evaluate to a bool. For advisory rules, True means the obligation is triggered.",
    )
    message: str = Field(
        ...,
        description="str.format template; may use {measured} and {limit} with format specs.",
    )
    compiled_by: str = Field(
        ...,
        description="'human' or 'agent:<model-id>@<prompt-version>'.",
        pattern="^(human|agent:.+@.+)$",
    )
    freshness: common_schema.Freshness | None = None
    metric: Metric | None = Field(
        None, description="Tag used by the FSI headroom summary."
    )
    fix_unit: str | None = Field(
        None, description="Unit shown with fix_by, e.g. 'm', 'm2'. Null = no unit."
    )
    guidance_note: GuidanceNote | None = Field(
        None,
        description="Note from a reference-only document (e.g. NBCS 2026). Never affects status.",
    )
    review_notes: str | None = Field(
        None,
        description="Notes from the reviewer model (scripts/compile_rule.py --review).",
    )
