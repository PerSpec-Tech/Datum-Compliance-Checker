# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Common(RootModel[Any]):
    root: Any = Field(
        ...,
        description="Shared types for the compliance checker contracts (ROADMAP §5). Units are SI: metres, m², decimal degrees.",
        title="Common",
    )


class Source(StrEnum):
    """
    Where a fact came from (D4). 'declared' always wins over the others.
    """

    model = "model"
    inferred = "inferred"
    declared = "declared"
    default = "default"


class Point2(RootModel[list[float]]):
    """
    [x, y] in project coordinates, metres.
    """

    root: list[float] = Field(
        ...,
        description="[x, y] in project coordinates, metres.",
        max_length=2,
        min_length=2,
    )


class Polygon(RootModel[list[Point2]]):
    """
    Closed implicitly (last point is not repeated), counter-clockwise.
    """

    root: list[Point2] = Field(
        ...,
        description="Closed implicitly (last point is not repeated), counter-clockwise.",
        min_length=3,
    )


class ElementKind(StrEnum):
    spaces = "spaces"
    areas = "areas"
    stairs = "stairs"
    doors = "doors"
    levels = "levels"
    units = "units"
    site_edges = "site.edges"
    site = "site"
    building = "building"


class ElementRef(BaseModel):
    """
    Points a result at one element. source_id is the Revit UniqueId or IFC GlobalId used to send results back.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: ElementKind
    id: str
    source_id: str | None


class Clause(BaseModel):
    """
    Citation copied from source text, never from memory (D13).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ref: str = Field(
        ..., description="Exactly as printed in the source, e.g. '14.2.1.2'."
    )
    excerpt: str = Field(..., description="Up to 2 sentences, verbatim.")
    source: str = Field(
        ..., description="Manifest doc id + printed page, e.g. 'udcpr2020 p.266'."
    )
    retrieved: date | None = None


class FreshnessStatus(StrEnum):
    unchecked = "unchecked"
    current = "current"
    possibly_superseded = "possibly_superseded"


class Freshness(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    status: FreshnessStatus
    url: str | None
    checked: date | None


class Usage(StrEnum):
    habitable = "habitable"
    bedroom = "bedroom"
    living = "living"
    kitchen = "kitchen"
    bathroom = "bathroom"
    wc = "wc"
    corridor = "corridor"
    stair = "stair"
    lobby = "lobby"
    parking = "parking"
    office = "office"
    retail = "retail"
    assembly = "assembly"
    storage = "storage"
    utility = "utility"
    other = "other"


class EdgeKind(StrEnum):
    road = "road"
    neighbour = "neighbour"
    open_space = "open_space"


class RoadWidthBasis(StrEnum):
    existing = "existing"
    development_plan = "development_plan"


class BuildingType(StrEnum):
    group_housing = "group_housing"
    standalone = "standalone"
    bungalow_self_use = "bungalow_self_use"
    mixed_use = "mixed_use"
    other = "other"


class UnitUse(StrEnum):
    residential = "residential"
    commercial = "commercial"
    office = "office"
    other = "other"


class OccupancyGroup(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"
    J = "J"


class LineStatus(StrEnum):
    operational = "operational"
    under_construction = "under_construction"
    proposed = "proposed"
    unknown = "unknown"


class LatLon(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


class Occupancy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group: OccupancyGroup
    subdivision: str | None = Field(
        ..., description="e.g. 'A-4', as printed in the source."
    )


class MetroStation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    line: str | None
    status: LineStatus
    distance_m: float = Field(..., ge=0.0)


class FactNumber(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: float | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactString(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: str | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactBool(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: bool | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactStringList(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: list[str] | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactLatLon(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: LatLon | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactOccupancy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: Occupancy | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactMetroStation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: MetroStation | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactUsage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: Usage | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactEdgeKind(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: EdgeKind | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactRoadWidthBasis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: RoadWidthBasis | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactBuildingType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: BuildingType | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class FactUnitUse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: UnitUse | None
    source: Source
    note: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)
