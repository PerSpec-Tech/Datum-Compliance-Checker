# GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, RootModel

from . import common_schema


class Kind(StrEnum):
    map = "map"
    bands = "bands"
    map_of_bands = "map_of_bands"


class Value(RootModel[float | str | bool | None]):
    root: float | str | bool | None


class Band(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    min: float = Field(..., description="Inclusive.")
    max: float | None = Field(..., description="Exclusive; null = no upper bound.")
    value: Value | None


class LookupTable(BaseModel):
    """
    Lookup table used by rule expressions via table(name, *keys). Stored under rules/<ruleset>/tables/<name>.yaml.
    - map: table(name, key) → entries[key]
    - bands: table(name, x) → value of the band with min <= x < max (max null = no upper bound)
    - map_of_bands: table(name, key, x) → bands of map[key], then as 'bands'
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="Unique; referenced as table('<name>', ...).",
        pattern="^[a-z0-9_]+(\\.[a-z0-9_-]+)+$",
    )
    authority: str = Field(..., pattern="^[a-z0-9_]+$")
    description: str | None = None
    unit: str | None = Field(None, description="Unit of the values, e.g. 'm', 'fsi'.")
    source: common_schema.Clause
    kind: Kind
    map: dict[str, Value | None] | None = Field(
        None,
        description="kind=map. Keys are strings; numeric keys are written as strings.",
    )
    bands: list[Band] | None = Field(None, description="kind=bands.")
    map_of_bands: dict[str, list[Band]] | None = Field(
        None, description="kind=map_of_bands."
    )
