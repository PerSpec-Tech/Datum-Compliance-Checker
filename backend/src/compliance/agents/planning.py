"""Planning facts suggested from the model and the site. Deterministic: no LLM.

Every suggestion is `inferred`, carries a note saying where it came from, and never replaces a value
from the model or one the architect declared. The web app shows them dashed, one click to
confirm.

- building type and occupancy: from the rooms and units (NBC 2016 Part 4, 3.1.1.2 and 3.1.2);
- congested area: UDCPR p.105 means the congested (core) area "as shown on the Development Plan",
  and PMC publishes no GIS layer of it, so the suggestion comes from the street-level locality
  (rules/cities/<authority>/data/congested_localities.yaml);
- zone: the OpenStreetMap land use at the pin, which is the actual use, not the DP zone.
"""

from __future__ import annotations

import re
from datetime import timedelta
from functools import lru_cache
from typing import Any

import httpx
import yaml

from compliance.agents.authority import _reverse
from compliance.config import get_settings
from compliance.store.repo import Store

# Public Overpass servers are often busy (502/504): try the main one, then a mirror.
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
CACHE_AGE = timedelta(days=30)
LOCALITY_KEYS = ("suburb", "neighbourhood", "quarter", "city_district")
# OpenStreetMap land use → a zone word as DP sheets use it.
LANDUSE_ZONE = {
    "residential": "residential",
    "commercial": "commercial",
    "retail": "commercial",
    "industrial": "industrial",
    "education": "public / semi-public",
    "institutional": "public / semi-public",
    "religious": "public / semi-public",
    "military": "defence",
    "railway": "transport",
    "recreation_ground": "recreational / open space",
    "park": "recreational / open space",
    "grass": "recreational / open space",
    "farmland": "agricultural",
    "meadow": "agricultural",
    "orchard": "agricultural",
    "forest": "forest",
    "cemetery": "public / semi-public",
}
_PUBLIC = "public / semi-public"
_AMENITY_ZONE = {"school": _PUBLIC, "college": _PUBLIC, "university": _PUBLIC, "hospital": _PUBLIC}
_LEISURE_ZONE = {"park": "recreational / open space", "playground": "recreational / open space"}


# ------------------------------------------------------------------ site lookups (network, cached)


def lookup(
    lat: float,
    lon: float,
    store: Store | None = None,
    http: httpx.Client | None = None,
    *,
    cached_only: bool = False,
) -> dict[str, Any]:
    """Locality (Nominatim) and land use (Overpass) at a point. Missing parts are None.

    Overpass can take a minute, so a check passes `cached_only`: it uses the land use the web app
    looked up when the pin was placed (GET /suggestions), and never waits for Overpass itself.
    """
    out: dict[str, Any] = {"locality": None, "landuse": None, "landuse_name": None}
    try:
        a = _reverse(lat, lon, store, http)
        out["locality"] = next((a[k] for k in LOCALITY_KEYS if a.get(k)), None)
    except (httpx.HTTPError, ValueError):
        pass
    try:
        out.update(_landuse(lat, lon, store, http, cached_only))
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return out


def _landuse(
    lat: float, lon: float, store: Store | None, http: httpx.Client | None, cached_only: bool
) -> dict[str, Any]:
    key = f"overpass-landuse:{lat:.4f},{lon:.4f}"
    if store is not None and (hit := store.cache_get(key, CACHE_AGE)) is not None:
        return hit
    if cached_only:
        return {}
    q = (
        f"[out:json][timeout:20];is_in({lat},{lon})->.a;"
        'area.a[~"^(landuse|amenity|leisure)$"~"."];out tags;'
    )
    client = http or httpx.Client(timeout=30)
    for i, url in enumerate(OVERPASS):
        try:
            resp = client.post(
                url, data={"data": q}, headers={"User-Agent": get_settings().nominatim_user_agent}
            )
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            if i == len(OVERPASS) - 1:
                raise
    found: dict[str, Any] = {"landuse": None, "landuse_name": None}
    for el in resp.json()["elements"]:  # smallest areas aren't guaranteed first: prefer landuse
        t = el.get("tags", {})
        zone = (
            LANDUSE_ZONE.get(t.get("landuse", ""))
            or _AMENITY_ZONE.get(t.get("amenity", ""))
            or _LEISURE_ZONE.get(t.get("leisure", ""))
        )
        if zone and (found["landuse"] is None or "landuse" in t):
            found = {"landuse": zone, "landuse_name": t.get("name")}
    if store is not None:
        store.cache_put(key, "overpass", {"lat": lat, "lon": lon}, found)
    return found


# ------------------------------------------------------------------ suggestions (pure)


@lru_cache
def _congested_table(authority_id: str) -> dict[str, Any] | None:
    path = get_settings().rules_dir / "cities" / authority_id / "data" / "congested_localities.yaml"
    return yaml.safe_load(path.read_text("utf-8")) if path.exists() else None


def congested(locality: str | None, authority_id: str | None) -> dict[str, Any] | None:
    table = _congested_table(authority_id) if authority_id else None
    if table is None or not locality:
        return None
    hit = any(re.search(p, locality, re.IGNORECASE) for p in table["patterns"])
    note = (table["note_in"] if hit else table["note_out"]).format(locality=locality)
    return {"value": hit, "source": "inferred", "confidence": 0.6, "note": note}


def zone(site: dict[str, Any]) -> dict[str, Any] | None:
    if not site.get("landuse"):
        return None
    where = f" ({site['landuse_name']})" if site.get("landuse_name") else ""
    return {
        "value": site["landuse"],
        "source": "inferred",
        "confidence": 0.5,
        "note": f"OpenStreetMap land use at the pin{where}: the actual use, not the DP zone. "
        "Confirm on the DP sheet. © OpenStreetMap contributors",
    }


def building(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Building type and occupancy from the rooms and units."""
    units = model.get("units") or []
    spaces = model.get("spaces") or []
    usage = [s["usage"]["value"] for s in spaces]
    flats = sum(1 for u in units if u["use"]["value"] == "residential") or usage.count("kitchen")
    shops = sum(1 for u in units if u["use"]["value"] in ("commercial", "office")) or sum(
        1 for x in usage if x in ("retail", "office")
    )
    if not flats and not shops:
        return {}
    counted = "units" if units else "rooms"
    what = ", ".join(
        p for p in (f"{flats} dwelling{'s' * (flats != 1)}" if flats else "",
                    f"{shops} shop/office{'s' * (shops != 1)}" if shops else "") if p
    )  # fmt: skip
    note = f"from the model's {counted}: {what}"

    def fact(value: Any, confidence: float, why: str) -> dict[str, Any]:
        return {"value": value, "source": "inferred", "confidence": confidence,
                "note": f"{note}; {why}"}  # fmt: skip

    if flats:
        sub = "A-2" if flats <= 2 else "A-4"
        sub_name = {"A-2": "One or two family private dwellings", "A-4": "Apartment houses"}[sub]
        occ = fact({"group": "A", "subdivision": sub}, 0.7,
                   f"NBC 2016 Part 4, 3.1.2: Subdivision {sub} {sub_name}")  # fmt: skip
        if shops:
            kind = fact("mixed_use", 0.7, "shops with dwellings: NBC 2016 Part 4, 3.1.1.2 "
                        "Mixed occupancy")  # fmt: skip
        elif flats <= 2:
            kind = fact("bungalow_self_use", 0.5, "one or two dwellings: assumed for the owner's "
                        "own use; change it if the flats are for sale")  # fmt: skip
        else:
            kind = fact("standalone", 0.6, "flats in one building on the plot")
        return {"project.occupancy": occ, "project.building_type": kind}
    retail = "retail" in usage or any(u["use"]["value"] == "commercial" for u in units)
    group = "F" if retail else "E"
    name = "Mercantile" if retail else "Business"
    return {
        "project.occupancy": fact({"group": group, "subdivision": None}, 0.6,
                                  f"NBC 2016 Part 4: Group {group} {name}"),
        "project.building_type": fact("other", 0.6, "no dwellings"),
    }  # fmt: skip


def suggest(model: dict[str, Any], site: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """path → suggested fact, for every fact this module can suggest (whatever the model has)."""
    out = building(model)
    if site:
        authority = model["project"]["authority_id"]["value"] or "pmc"
        if c := congested(site.get("locality"), authority):
            out["project.congested_area"] = c
        if z := zone(site):
            out["project.zone"] = z
    return out


def apply(model: dict[str, Any], site: dict[str, Any] | None) -> str | None:
    """Fill facts the model and the architect left open. Returns a progress message."""
    project = model["project"]
    used = []
    for path, fact in suggest(model, site).items():
        key = path.removeprefix("project.")
        if project[key]["source"] in ("model", "declared"):
            continue
        project[key] = fact
        used.append(_LABEL[key](fact["value"]))
    return ("suggested: " + "; ".join(used)) if used else None


_LABEL = {
    "occupancy": lambda v: f"occupancy {v['subdivision'] or v['group']}",
    "building_type": lambda v: v.replace("_", " "),
    "congested_area": lambda v: "congested area" if v else "not a congested area",
    "zone": lambda v: f"{v} land use",
}
