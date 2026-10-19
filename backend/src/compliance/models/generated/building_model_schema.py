# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from . import common_schema


class SourceKind(StrEnum):
    revit = "revit"
    ifc = "ifc"
    manual = "manual"


class Meta(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    source_kind: SourceKind
    source_file: str | None
    exported_at: AwareDatetime
    tool_version: str | None


class Level(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    name: str
    elevation_m: float
    is_basement: bool


class Special(BaseModel):
    """
    Declared yes/no constraints (D19). metro_rail_within_20m triggers the Metro NOC advisory (UDCPR 14.2.1.7).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    heritage: common_schema.FactBool
    coastal: common_schema.FactBool
    airport_zone: common_schema.FactBool
    ht_line: common_schema.FactBool
    railway: common_schema.FactBool
    river_flood_line: common_schema.FactBool
    hill_slope_bdp: common_schema.FactBool
    defence_vicinity: common_schema.FactBool
    metro_rail_within_20m: common_schema.FactBool


class Overlays(BaseModel):
    """
    Spatial overlays (D18, D22).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    nearest_metro_station: common_schema.FactMetroStation
    metro_tod: common_schema.FactBool
    plot_share_in_tod: common_schema.FactNumber = Field(
        ..., description="0..1; declared only in v1 (UDCPR 14.2.1.2.4)."
    )


class Project(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    location: common_schema.FactLatLon
    authority_id: common_schema.FactString = Field(
        ..., description="e.g. 'pmc'; matches rules/cities/<id>/."
    )
    rulesets: common_schema.FactStringList = Field(
        ...,
        description="Ordered, later overrides earlier, e.g. [nbc2016, udcpr2020, pmc] (D15).",
    )
    occupancy: common_schema.FactOccupancy
    zone: common_schema.FactString = Field(
        ..., description="Development Plan land-use zone, as declared."
    )
    congested_area: common_schema.FactBool = Field(
        ...,
        description="Plot lies in a congested area as shown in the Development Plan / Gaothan (UDCPR 6.1 vs 6.2 margins and FSI). Declared.",
    )
    special: Special
    building_type: common_schema.FactBuildingType
    overlays: Overlays


class Edge(BaseModel):
    """
    One side of the plot boundary. Road width is a legal fact: declared, never measured (D5).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    a: common_schema.Point2
    b: common_schema.Point2
    kind: common_schema.FactEdgeKind
    road_width_m: common_schema.FactNumber
    road_width_basis: common_schema.FactRoadWidthBasis


class Site(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    boundary: common_schema.Polygon | None = Field(
        ...,
        description="From property lines. Null means site checks can't be verified.",
    )
    plot_area_declared_m2: common_schema.FactNumber = Field(
        ..., description="Plot area as per ownership documents."
    )
    is_corner_plot: common_schema.FactBool
    ground_level_m: float | None
    edges: list[Edge]


class Building(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    footprint: common_schema.Polygon | None
    roof_top_m: float | None = Field(
        ..., description="Elevation of the highest roof/terrace finish."
    )
    highest_point_m: float | None = Field(
        ..., description="Elevation of the highest point of any element."
    )


class Space(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    name: str
    level_id: str
    usage: common_schema.FactUsage
    area_m2: float | None = Field(..., ge=0.0)
    clear_height_m: float | None = Field(..., ge=0.0)
    polygon: common_schema.Polygon | None


class Area(BaseModel):
    """
    Revit Area (area plan) or equivalent, used for built-up / FSI.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    scheme: str
    level_id: str
    name: str
    area_m2: float | None = Field(..., ge=0.0)
    counts_to_far: common_schema.FactBool


class Stair(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    base_level_id: str
    top_level_id: str | None
    min_run_width_m: float | None = Field(..., ge=0.0)
    riser_m: float | None = Field(..., ge=0.0)
    tread_m: float | None = Field(..., ge=0.0)
    is_exit: common_schema.FactBool


class Door(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    level_id: str
    width_m: float | None = Field(..., ge=0.0)
    height_m: float | None = Field(..., ge=0.0)
    is_exit: common_schema.FactBool
    from_space_id: str | None
    to_space_id: str | None


class Unit(BaseModel):
    """
    A tenement / flat (TOD 14.2.1.3).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    source_id: str | None
    name: str
    level_id: str
    carpet_area_m2: float | None = Field(..., ge=0.0)
    use: common_schema.FactUnitUse


class BuildingModel(BaseModel):
    """
    One building, normalised from Revit or IFC (ROADMAP §5.1). SI units. Any measured value may be null; the engine then reports 'cannot verify'.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Literal["1.0"]
    field_notes: list[str] | None = Field(
        None,
        alias="_notes",
        description="Free-text notes for hand-written fixtures (e.g. the list of deliberate failures). Ignored by the engine.",
    )
    meta: Meta
    project: Project
    site: Site
    levels: list[Level]
    building: Building
    spaces: list[Space]
    areas: list[Area]
    stairs: list[Stair]
    doors: list[Door]
    units: list[Unit]
