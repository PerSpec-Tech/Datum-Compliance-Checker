"""Derived values computed from a BuildingModel, exposed as `derived.*`.

Each value is either a number (or a dict of numbers), or None when an input is missing. `INPUTS`
says which model paths each value depends on, so a rule that can't be checked because, say,
`derived.far` is None can ask for the plot area instead of for "FAR".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Polygon

# derived name → model paths it is computed from (used to turn "derived.x missing" into questions)
INPUTS: dict[str, list[str]] = {
    "plot_area_m2": ["site.plot_area_declared_m2", "site.boundary"],
    "footprint_area_m2": ["building.footprint"],
    "ground_coverage": ["building.footprint", "site.plot_area_declared_m2", "site.boundary"],
    "built_up_m2": ["areas[*].area_m2", "areas[*].counts_to_far"],
    "far": ["areas[*].area_m2", "areas[*].counts_to_far", "site.plot_area_declared_m2"],
    "building_height_m": ["building.roof_top_m", "site.ground_level_m"],
    "floors_above_ground": ["levels"],
    "setback_m": ["building.footprint", "site.edges"],
    "road_edges": ["site.edges[*].kind"],
    "front_road_width_m": ["site.edges[*].kind", "site.edges[*].road_width_m"],
    "space_min_width_m": ["spaces[*].polygon"],
    "space_min_length_m": ["spaces[*].polygon"],
    "residential_carpet_m2": ["units[*].carpet_area_m2", "units[*].use"],
    "small_unit_carpet_share": ["units[*].carpet_area_m2", "units[*].use"],
}

SMALL_UNIT_MAX_M2 = 60.0  # UDCPR 14.2.1.3 "size equal to or less than 60 sq.m. carpet area"


@dataclass(frozen=True)
class Derived:
    values: dict[str, Any]
    # derived name → facts it was computed from ({path, value, source}), so results can show
    # e.g. the declared road width behind `derived.front_road_width_m`.
    facts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # derived name → the exact model inputs that are missing (empty when the value is known).
    missing: dict[str, list[str]] = field(default_factory=dict)

    def inputs_for(self, path: str) -> list[str]:
        """Inputs behind a missing 'derived.x…' path: the precise gaps if known, else INPUTS."""
        if not path.startswith("derived."):
            return [path]
        name = path[len("derived.") :].split(".", 1)[0].split("[", 1)[0]
        return self.missing.get(name) or INPUTS.get(name, [path])

    def as_ctx(self) -> dict[str, Any]:
        return self.values


def _fact_value(v: Any) -> Any:
    return v.get("value") if isinstance(v, Mapping) and "source" in v else v


def _poly(coords: Any) -> Polygon | None:
    if not coords or len(coords) < 3:
        return None
    p = Polygon(coords)
    if p.area <= 0:
        return None
    return p if p.is_valid else p.buffer(0)  # buffer(0) repairs self-touching outlines


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute(model: Mapping[str, Any]) -> Derived:
    site, building = model["site"], model["building"]

    # Plot area: declared (legal) wins; otherwise the property-line polygon, marked as model.
    declared = _fact_value(site["plot_area_declared_m2"])
    boundary = _poly(site.get("boundary"))
    if declared is not None:
        plot_area = {"value": float(declared), "source": "declared"}
    elif boundary is not None:
        plot_area = {
            "value": round(boundary.area, 4),
            "source": "model",
            "note": "measured from property lines; documents may differ",
        }
    else:
        plot_area = {"value": None, "source": "default"}
    plot = plot_area["value"]

    footprint = _poly(building.get("footprint"))
    footprint_area = round(footprint.area, 4) if footprint is not None else None

    plot_missing = [] if plot is not None else ["site.plot_area_declared_m2", "site.boundary"]

    # Built-up area for FSI: every area must say whether it counts and have an area value.
    built_up: float | None = None
    areas = model.get("areas") or []
    area_missing: list[str] = [] if areas else ["areas"]
    for a in areas:
        counts, area = _fact_value(a["counts_to_far"]), a["area_m2"]
        if counts is None:
            area_missing.append(f"areas[{a['id']}].counts_to_far")
        elif counts and area is None:
            area_missing.append(f"areas[{a['id']}].area_m2")
    if areas and not area_missing:
        built_up = round(sum(a["area_m2"] for a in areas if _fact_value(a["counts_to_far"])), 4)

    ground, roof = site.get("ground_level_m"), building.get("roof_top_m")
    height = round(roof - ground, 4) if roof is not None and ground is not None else None

    floors = sum(1 for lv in model.get("levels") or [] if not lv["is_basement"])

    setbacks: dict[str, float] = {}
    if footprint is not None:
        for e in site.get("edges") or []:
            setbacks[e["id"]] = round(footprint.distance(LineString([e["a"], e["b"]])), 4)

    # Front road: the widest road edge. Unknown if any road edge's width is unknown.
    edges = site.get("edges") or []
    road_edges = [e["id"] for e in edges if _fact_value(e["kind"]) == "road"]
    road_missing = [f"site.edges[{e['id']}].kind" for e in edges if _fact_value(e["kind"]) is None]
    road_missing += [
        f"site.edges[{e['id']}].road_width_m"
        for e in edges
        if e["id"] in road_edges and _fact_value(e["road_width_m"]) is None
    ]
    if not edges:
        road_missing = ["site.edges"]
    elif not road_edges and not road_missing:
        road_missing = ["site.edges"]  # every edge tagged, but none is a road
    front_road: float | None = None
    if not road_missing:
        front_road = max(_fact_value(e["road_width_m"]) for e in edges if e["id"] in road_edges)

    min_widths: dict[str, float] = {}
    min_lengths: dict[str, float] = {}
    for sp in model.get("spaces") or []:
        poly = _poly(sp.get("polygon"))
        if poly is None:
            continue
        rect = poly.minimum_rotated_rectangle
        xs = list(rect.exterior.coords)
        sides = [LineString([xs[i], xs[i + 1]]).length for i in range(len(xs) - 1)]
        min_widths[sp["id"]] = round(min(sides), 4)
        min_lengths[sp["id"]] = round(max(sides), 4)

    # Tenement mix (TOD 14.2.1.3): share of residential carpet area in units ≤ 60 sq.m.
    residential_carpet: float | None = None
    small_share: float | None = None
    units = model.get("units") or []
    uses = [_fact_value(u["use"]) for u in units]
    unit_missing = [
        f"units[{u['id']}].use" for u, use in zip(units, uses, strict=True) if use is None
    ]
    unit_missing += [
        f"units[{u['id']}].carpet_area_m2"
        for u, use in zip(units, uses, strict=True)
        if use == "residential" and u["carpet_area_m2"] is None
    ]
    if not units:
        unit_missing = ["units"]
    if units and None not in uses:
        res = [u for u, use in zip(units, uses, strict=True) if use == "residential"]
        if res and all(u["carpet_area_m2"] is not None for u in res):
            residential_carpet = round(sum(u["carpet_area_m2"] for u in res), 4)
            small = sum(
                u["carpet_area_m2"] for u in res if u["carpet_area_m2"] <= SMALL_UNIT_MAX_M2
            )
            small_share = round(_div(small, residential_carpet), 6)

    plot_facts = (
        [{"path": "derived.plot_area_m2", "value": plot, "source": plot_area["source"]}]
        if plot is not None
        else []
    )
    edge_facts = [
        {"path": f"site.edges[{e['id']}].{k}", "value": _fact_value(e[k]), "source": e[k]["source"]}
        for e in edges
        if e["id"] in road_edges
        for k in ("kind", "road_width_m", "road_width_basis")
    ]
    return Derived(
        {
            "plot_area_m2": plot_area,
            "footprint_area_m2": footprint_area,
            "ground_coverage": _round(_div(footprint_area, plot)),
            "built_up_m2": built_up,
            "far": _round(_div(built_up, plot)),
            "building_height_m": height,
            "floors_above_ground": floors,
            "setback_m": setbacks,
            "road_edges": road_edges,
            "front_road_width_m": front_road,
            "space_min_width_m": min_widths,
            "space_min_length_m": min_lengths,
            "residential_carpet_m2": residential_carpet,
            "small_unit_carpet_share": small_share,
        },
        missing={
            "plot_area_m2": plot_missing,
            "footprint_area_m2": [] if footprint is not None else ["building.footprint"],
            "ground_coverage": ([] if footprint is not None else ["building.footprint"])
            + plot_missing,
            "built_up_m2": area_missing,
            "far": area_missing + plot_missing,
            "building_height_m": ([] if roof is not None else ["building.roof_top_m"])
            + ([] if ground is not None else ["site.ground_level_m"]),
            "setback_m": ["building.footprint"]
            if footprint is None
            else ([] if edges else ["site.edges"]),
            "road_edges": road_missing,
            "front_road_width_m": road_missing,
            "residential_carpet_m2": unit_missing,
            "small_unit_carpet_share": unit_missing,
        },
        facts={
            "ground_coverage": plot_facts,
            "far": plot_facts,
            "road_edges": edge_facts,
            "front_road_width_m": edge_facts,
        },
    )


def _round(v: float | None, digits: int = 6) -> float | None:
    return None if v is None else round(v, digits)


def inputs_for(path: str) -> list[str]:
    """Model inputs behind a missing 'derived.x…' path; other paths are returned unchanged."""
    if not path.startswith("derived."):
        return [path]
    name = path[len("derived.") :].split(".", 1)[0].split("[", 1)[0]
    return INPUTS.get(name, [path])
