# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel

from . import common_schema


class Status(StrEnum):
    pass_ = "pass"
    fail = "fail"
    unverifiable = "unverifiable"
    not_applicable = "not_applicable"
    advisory = "advisory"


class Summary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pass_: int = Field(..., alias="pass", ge=0)
    fail: int = Field(..., ge=0)
    unverifiable: int = Field(..., ge=0)
    not_applicable: int = Field(..., ge=0)
    advisory: int = Field(..., ge=0)


class Scalar(RootModel[float | str | bool | None]):
    root: float | str | bool | None


class FixDirection(StrEnum):
    increase = "increase"
    decrease = "decrease"


class FixBy(BaseModel):
    """
    How much the measured value must change to pass (D30). Only for comparison failures.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    amount: float = Field(..., ge=0.0)
    unit: str | None
    direction: FixDirection


class Severity(StrEnum):
    critical = "critical"
    major = "major"
    minor = "minor"


class RuleStatus(StrEnum):
    draft = "draft"
    verified = "verified"


class GuidanceNote(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    text: str
    source: str


class InputType(StrEnum):
    number = "number"
    enum = "enum"
    bool = "bool"
    latlon = "latlon"
    edge_tags = "edge_tags"
    text = "text"


class Question(BaseModel):
    """
    A missing input, ranked by how many checks it unlocks (P2.5).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: str
    prompt: str
    unlocks: int = Field(..., ge=0)
    rule_ids: list[str]
    input_type: InputType
    options: list[str] | None


class FsiSummary(BaseModel):
    """
    FSI used vs permitted, built only from rule-table limits (P2.8, D30). Numbers are null when inputs are missing.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    plot_area_m2: float | None
    built_up_m2: float | None
    used: float | None
    base_permissible: float | None
    max_permissible: float | None
    basis: list[str]
    headroom_base_m2: float | None = Field(
        ..., description="Negative = over the limit."
    )
    headroom_max_m2: float | None
    rule_ids: list[str]
    missing_inputs: list[str]


class FactUsed(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: str = Field(..., description="e.g. 'site.edges[e2].road_width_m'.")
    value: Any = Field(..., description="The value that was read (any JSON).")
    source: common_schema.Source


class Result(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: str
    title: str
    severity: Severity
    element: common_schema.ElementRef | None
    status: Status
    measured: Scalar | None
    limit: Scalar | None
    message: str
    missing_inputs: list[str]
    facts_used: list[FactUsed]
    clause: common_schema.Clause
    rule_status: RuleStatus
    freshness: common_schema.Freshness
    fix_by: FixBy | None
    guidance_note: GuidanceNote | None = None


class CheckReport(BaseModel):
    """
    Result of one compliance check job (ROADMAP §5.4). Pass/fail comes only from engine/evaluate.py; agents only add wording (explanation) and freshness.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    project_id: str
    model_version: str = Field(
        ..., description="Id of the BuildingModel version that was checked."
    )
    ruleset_version: str = Field(
        ..., description="Hash of all rule and table files used."
    )
    created_at: AwareDatetime
    summary: Summary
    results: list[Result]
    questions: list[Question]
    explanation: str | None = Field(
        ..., description="Plain-language summary from the explainer agent (P3.8)."
    )
    fsi: FsiSummary | None
