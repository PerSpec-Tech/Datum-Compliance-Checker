"""Planning-authority resolver (P3.4, location part). Deterministic: no LLM.

Location → OpenStreetMap Nominatim reverse geocode (cached 30 days, ≤ 1 request/s, User-Agent set)
→ match against rules/cities/*/authority.yaml. If Nominatim can't be reached, an authority's
optional offline `bbox` is used instead (marked as such). Unsupported places return no rule sets;
the Tavily discovery part of P3.4 is added once a Tavily key is configured.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from typing import Any

import httpx
import yaml

from compliance.config import get_settings
from compliance.store.repo import Store

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
CACHE_AGE = timedelta(days=30)
_rate_lock = threading.Lock()
_last_call = 0.0


@dataclass
class Resolution:
    authority_id: str | None
    rulesets: list[str] | None
    note: str
    address: dict[str, Any] = field(default_factory=dict)


@lru_cache
def authorities() -> list[dict[str, Any]]:
    root = get_settings().rules_dir / "cities"
    return [yaml.safe_load(p.read_text("utf-8")) for p in sorted(root.glob("*/authority.yaml"))]


def resolve(
    lat: float, lon: float, store: Store | None = None, http: httpx.Client | None = None
) -> Resolution:
    try:
        address = _reverse(lat, lon, store, http)
    except (httpx.HTTPError, ValueError) as e:
        for a in authorities():
            if _in_bbox(a, lat, lon):
                return Resolution(
                    a["id"],
                    list(a["rulesets"]),
                    f"{a['name']} (from the offline area box; address lookup failed: {e})",
                )
        return Resolution(None, None, f"address lookup failed and no offline area matched: {e}")

    for a in authorities():
        if _matches(a, address):
            return Resolution(
                a["id"], list(a["rulesets"]), f"{a['name']} (from the site address)", address
            )
    place = (
        address.get("city")
        or address.get("town")
        or address.get("county")
        or address.get("state")
        or "this location"
    )
    return Resolution(
        None, None, f"{place} is not covered yet (pilot: Pune Municipal Corporation)", address
    )


# Street level. At town level (zoom 12) Nominatim names the nearest town, not the one the point is
# in: Bund Garden (inside PMC) came back as "Khadki".
ZOOM = 18


def _reverse(
    lat: float, lon: float, store: Store | None, http: httpx.Client | None, zoom: int = ZOOM
) -> dict[str, Any]:
    key = f"nominatim:{lat:.4f},{lon:.4f}:z{zoom}"
    if store is not None and (hit := store.cache_get(key, CACHE_AGE)) is not None:
        return hit
    _throttle()
    client = http or httpx.Client(timeout=10)
    resp = client.get(
        NOMINATIM,
        params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": zoom, "addressdetails": 1},
        headers={"User-Agent": get_settings().nominatim_user_agent, "Accept-Language": "en"},
    )
    resp.raise_for_status()
    address = resp.json().get("address") or {}
    if not address:
        raise ValueError("no address returned")
    if store is not None:
        store.cache_put(key, "nominatim", {"lat": lat, "lon": lon}, address)
    return address


def place_label(lat: float, lon: float, store: Store | None = None) -> str | None:
    """Street-level name for a map pin, e.g. "Deccan Gymkhana, Pune". None if the lookup fails."""
    try:
        a = _reverse(lat, lon, store, None)
    except (httpx.HTTPError, ValueError):
        return None
    keys = ("road", "neighbourhood", "suburb", "quarter", "city_district")
    parts = [a.get(k) for k in keys if a.get(k)][:2] + [a.get("city") or a.get("town")]
    return ", ".join(dict.fromkeys(p for p in parts if p)) or None


def _throttle() -> None:
    global _last_call
    with _rate_lock:  # Nominatim usage policy: at most 1 request per second
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def search(
    query: str, authority_id: str, store: Store | None = None, http: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Address → up to 5 places inside the authority's area (web app location step)."""
    a = next((x for x in authorities() if x["id"] == authority_id), None)
    if a is None:
        raise ValueError(f"unknown authority {authority_id!r}")
    q = " ".join(query.split())
    key = f"nominatim-search:{authority_id}:{q.lower()}"
    if store is not None and (hit := store.cache_get(key, CACHE_AGE)) is not None:
        return hit["places"]
    b = a["bbox"]
    _throttle()
    client = http or httpx.Client(timeout=10)
    resp = client.get(
        NOMINATIM_SEARCH,
        params={
            "format": "jsonv2", "q": q, "limit": 5, "countrycodes": "in", "bounded": 1,
            "viewbox": f"{b['west']},{b['north']},{b['east']},{b['south']}",
        },
        headers={"User-Agent": get_settings().nominatim_user_agent, "Accept-Language": "en"},
    )  # fmt: skip
    resp.raise_for_status()
    places, seen = [], set()
    for r in resp.json():
        lat, lon = round(float(r["lat"]), 6), round(float(r["lon"]), 6)
        if (round(lat, 4), round(lon, 4)) in seen:  # same spot listed under two names
            continue
        seen.add((round(lat, 4), round(lon, 4)))
        places.append({"label": r["display_name"], "lat": lat, "lon": lon})
    if store is not None:
        store.cache_put(key, "nominatim", {"q": q, "authority": authority_id}, {"places": places})
    return places


PHOTON = "https://photon.komoot.io/api/"
# Photon place types, most precise first: an address is placed at once, an area is zoomed to.
_PRECISE = {"house", "building", "street"}


def suggest(
    query: str, authority_id: str, store: Store | None = None, http: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Search-as-you-type suggestions inside the authority's area (web site setup).

    Photon (OSM data, built for autocomplete) rather than Nominatim, whose usage policy forbids
    autocomplete. Each place carries its extent [west, south, east, north] when it is an area,
    so the map can zoom to a locality, and `precise` when it is an address or a street."""
    a = next((x for x in authorities() if x["id"] == authority_id), None)
    if a is None:
        raise ValueError(f"unknown authority {authority_id!r}")
    q = " ".join(query.split())
    key = f"photon:{authority_id}:{q.lower()}"
    if store is not None and (hit := store.cache_get(key, CACHE_AGE)) is not None:
        return hit["places"]
    b = a["bbox"]
    client = http or httpx.Client(timeout=6)
    resp = client.get(
        PHOTON,
        params={
            "q": q, "limit": 6, "lang": "en",
            "lat": (b["south"] + b["north"]) / 2, "lon": (b["west"] + b["east"]) / 2,
            "bbox": f"{b['west']},{b['south']},{b['east']},{b['north']}",
        },
        headers={"User-Agent": get_settings().nominatim_user_agent},
    )  # fmt: skip
    resp.raise_for_status()
    places, seen = [], set()
    for f in resp.json().get("features", []):
        p, (lon, lat) = f.get("properties", {}), f["geometry"]["coordinates"]
        parts = [p.get("name") or " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)]
        parts += [p.get(k) for k in ("street", "district", "locality", "city") if p.get(k)]
        label = ", ".join(dict.fromkeys(x for x in parts if x))
        if not label or label in seen:
            continue
        seen.add(label)
        ext = p.get("extent")  # [minLon, maxLat, maxLon, minLat]
        places.append({
            "label": label, "lat": round(lat, 6), "lon": round(lon, 6),
            "kind": p.get("type") or p.get("osm_value") or "place",
            "precise": (p.get("type") in _PRECISE) or ext is None,
            "extent": [ext[0], ext[3], ext[2], ext[1]] if ext else None,
        })  # fmt: skip
    if store is not None:
        store.cache_put(key, "photon", {"q": q, "authority": authority_id}, {"places": places})
    return places


def _matches(authority: dict[str, Any], address: dict[str, Any]) -> bool:
    m = authority.get("match") or {}
    names = {
        str(address.get(k, "")).strip().lower()
        for k in ("city", "town", "municipality", "city_district", "county", "state_district")
    } - {""}
    if any(c.lower() in names for c in m.get("exclude_city", [])):
        return False
    states = [s.lower() for s in m.get("state", [])]
    if states and str(address.get("state", "")).lower() not in states:
        return False
    if any(c.lower() in names for c in m.get("city", [])):
        return True
    county = str(address.get("county", "")).strip().lower()
    return bool(county) and county in {c.lower() for c in m.get("county", [])}


def _in_bbox(authority: dict[str, Any], lat: float, lon: float) -> bool:
    b = authority.get("bbox")
    return bool(b) and b["south"] <= lat <= b["north"] and b["west"] <= lon <= b["east"]
