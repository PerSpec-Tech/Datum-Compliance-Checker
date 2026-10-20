"""Metro TOD overlay (P3.10, D18, D22). Deterministic: no LLM.

Finds the nearest metro station to the site location (OpenStreetMap stations, checked against the
Pune Metro route map) and infers whether the site is in the TOD zone. UDCPR 14.2.1.1 measures 500 m
"around the … station boundary", but we only know station points, so:
  distance ≤ radius                → in the zone (inferred)
  distance ≥ radius + 75 m         → outside (inferred)  — 75 m ≈ half a station box
  in between, or a proposed line   → unknown → the planner asks the architect
A value the architect declared is never changed.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from compliance.config import get_settings
from compliance.engine.rules import RuleBase

STATION_HALF_LENGTH_M = 75.0
RADIUS_TABLE = "{authority}.tod_zone_radius"


@lru_cache
def stations(authority_id: str) -> list[dict[str, Any]]:
    path = get_settings().rules_dir / "cities" / authority_id / "data" / "metro_stations.geojson"
    if not path.exists():
        return []
    out = []
    for f in json.loads(path.read_text("utf-8"))["features"]:
        lon, lat = f["geometry"]["coordinates"]
        out.append({**f["properties"], "lat": lat, "lon": lon})
    return out


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine), metres."""
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def apply_overlays(model: dict[str, Any], rulebase: RuleBase) -> str | None:
    project = model["project"]
    authority = project["authority_id"]["value"]
    known = stations(authority) if authority else []
    if not known:
        return None
    loc = project["location"]["value"]
    overlays = project["overlays"]
    if not loc:
        return "no site location, so the nearest metro station is unknown"

    nearest = min(known, key=lambda s: distance_m(loc["lat"], loc["lon"], s["lat"], s["lon"]))
    d = round(distance_m(loc["lat"], loc["lon"], nearest["lat"], nearest["lon"]), 1)
    if overlays["nearest_metro_station"]["source"] != "declared":
        overlays["nearest_metro_station"] = {
            "value": {
                "name": nearest["name"],
                "line": nearest.get("line"),
                "status": nearest["status"],
                "distance_m": d,
            },
            "source": "inferred",
            "note": "straight-line distance from the site location to the station point "
            "(© OpenStreetMap contributors)",
        }
    station = f"{nearest['name']} ({nearest['status'].replace('_', ' ')}) is {d:.0f} m away"
    if overlays["metro_tod"]["source"] == "declared":
        return f"{station}; TOD zone as declared"

    table = rulebase.tables.get(RADIUS_TABLE.format(authority=authority))
    if table is None:
        return station
    radius = float(table["map"]["radius_m"])
    if d >= radius + STATION_HALF_LENGTH_M:
        tod, note = False, f"more than {radius:.0f} m from the nearest metro station"
    elif nearest["status"] == "proposed":
        tod, note = (
            None,
            (
                "the nearby station is on a proposed line; is the plot in the notified TOD zone "
                "(UDCPR 14.2.1.1)?"
            ),
        )
    elif d <= radius:
        tod, note = (
            True,
            f"within {radius:.0f} m of {nearest['name']} metro station (UDCPR 14.2.1.1)",
        )
    else:
        tod, note = (
            None,
            (
                f"{d:.0f} m from the station point: within the margin of the station boundary — "
                "check the TOD zone delineated by PMC"
            ),
        )
    overlays["metro_tod"] = (
        {"value": tod, "source": "inferred", "confidence": 0.8, "note": note}
        if tod is not None
        else {"value": None, "source": "default", "note": note}
    )
    verdict = {
        True: "inside the TOD zone",
        False: "outside the TOD zone",
        None: "TOD zone unclear — question added",
    }[tod]
    return f"{station}: {verdict}"
