# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class Point(RootModel[list[float]]):
    root: list[float] = Field(..., max_length=2, min_length=2)


class Ring(RootModel[list[Point]]):
    root: list[Point] = Field(..., min_length=3)


class EdgeMargin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edge_id: str
    a: Point
    b: Point
    kind: str | None
    margin_m: float | None = Field(
        ..., description="Null: the margin can't be known yet (a fact is missing)."
    )
    rule_id: str | None
    clause_ref: str | None
    margin_by_height: list[float | None] = Field(
        ...,
        description="The margin this side needs at building height i × height.step_m (i = 0, 1, …). Take the larger of the two samples around the live height. Empty when the margin doesn't depend on height or is unknown.",
    )


class FsiBudget(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    plot_area_m2: float | None
    base: float | None
    max: float | None
    base_built_up_m2: float | None
    max_built_up_m2: float | None
    used_m2: float | None = Field(
        ..., description="Built-up area at the time of the check."
    )
    rule_ids: list[str]


class HeightBand(BaseModel):
    """
    Heights for the margin tables: samples every step_m from 0 to max_m (floors held as in the check).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    current_m: float | None
    step_m: float
    max_m: float
    limit_m: float | None = Field(
        ...,
        description="The tallest the building may be on this plot as checked (the first sampled height a building-height rule fails, less one step); null when no rule limits it or it can't be known.",
    )
    limit_rule_id: str | None
    limit_clause_ref: str | None


class ForEach(StrEnum):
    spaces = "spaces"
    doors = "doors"
    stairs = "stairs"
    units = "units"


class Op(StrEnum):
    field__ = ">="
    field___1 = "<="
    field_ = ">"
    field__1 = "<"


class Threshold(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: str
    title: str
    clause_ref: str
    for_each: ForEach
    field: str = Field(
        ..., description="The element field the rule measures, e.g. clear_height_m."
    )
    op: Op
    limit: float
    element_ids: list[str]
    source_ids: list[str | None]


class LivePack(BaseModel):
    """
    P9.1 / D32: the rule engine's limits for one project, reduced to geometry the Revit and AutoCAD add-ins can test locally while the user models. A preview; the full check stays the official result.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    project_id: str
    model_version: str
    report_id: str = Field(..., description="The check this pack was compiled from.")
    ruleset_version: str
    created_at: AwareDatetime
    edges: list[EdgeMargin] = Field(
        ...,
        description="One entry per plot side with the margin the rules require from it.",
    )
    envelope: Ring | None = Field(
        ...,
        description="Buildable area: the plot inset by every side's margin. Null when a margin is unknown.",
    )
    fsi: FsiBudget
    height: HeightBand
    thresholds: list[Threshold] = Field(
        ...,
        description="Per-element limits that are constants for this project (room heights, stair and door widths).",
    )
    notes: list[str]
