"""fetch Pune metro stations from OpenStreetMap (Overpass API) once, check them against the
hand-typed reference list, and write rules/cities/pmc/data/metro_stations.geojson.

Usage: just fetch-stations [--write]

Without --write it only prints the comparison, so a person can resolve differences first.
Data © OpenStreetMap contributors, ODbL 1.0 — the attribution is kept in the GeoJSON.
"""

import json
import re
import sys
from datetime import UTC, datetime

import httpx
import yaml

from compliance.config import REPO_ROOT

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OVERPASS = "https://overpass-api.de/api/interpreter"
BBOX = "18.38,73.68,18.72,74.05"  # Pune + PCMC + Hinjawadi
QUERY = f"""
[out:json][timeout:90];
(
  nwr["railway"="station"]["station"~"subway|light_rail|monorail"]({BBOX});
  nwr["railway"="station"]["subway"="yes"]({BBOX});
  nwr["public_transport"="station"]["subway"="yes"]({BBOX});
  nwr["railway"="station"]["network"~"Metro",i]({BBOX});
  nwr["construction:railway"="station"]({BBOX});
  nwr["railway"="construction"]["construction"="station"]({BBOX});
  nwr["railway"="proposed"]["proposed"="station"]({BBOX});
  nwr["proposed:railway"="station"]({BBOX});
);
out center tags;
"""
DATA = REPO_ROOT / "rules" / "cities" / "pmc" / "data"
DEPOT = re.compile(r"depot", re.I)


def norm(name: str) -> str:
    n = name.lower().replace(".", "").replace(" ", " ")
    n = re.sub(r"\b(metro|station|stn)\b", " ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def dedupe(features: list[dict], within_m: float = 60.0) -> list[dict]:
    """Drop near-duplicate points (the same station mapped twice), preferring operational ones."""
    import math

    rank = {"operational": 0, "under_construction": 1, "proposed": 2}
    kept: list[dict] = []
    for f in sorted(features, key=lambda f: rank[f["properties"]["status"]]):
        lon, lat = f["geometry"]["coordinates"]
        close = False
        for k in kept:
            klon, klat = k["geometry"]["coordinates"]
            dx = (lon - klon) * 111_320 * math.cos(math.radians(lat))
            dy = (lat - klat) * 110_540
            if math.hypot(dx, dy) < within_m:
                close = True
                break
        if not close:
            kept.append(f)
    return kept


def status(tags: dict) -> str:
    if (
        tags.get("railway") == "construction"
        or "construction:railway" in tags
        or tags.get("construction") == "station"
    ):
        return "under_construction"
    if tags.get("railway") == "proposed" or "proposed:railway" in tags:
        return "proposed"
    return "operational"


def main() -> int:
    resp = httpx.post(
        OVERPASS,
        data={"data": QUERY},
        headers={
            "User-Agent": "PERSPEC-ComplianceChecker/0.1 (hackathon demo; Revit bylaw checker)"
        },
        timeout=120,
    )
    resp.raise_for_status()
    elements = resp.json()["elements"]

    ref = yaml.safe_load((DATA / "metro_reference.yaml").read_text("utf-8"))
    aliases = {norm(k): norm(v) for k, v in (ref.get("osm_aliases") or {}).items()}
    ref_line = {}
    for corridor, names in ref["operational_stations"].items():
        for n in names:
            ref_line[aliases.get(norm(n), norm(n))] = "1" if corridor == "corridor_1" else "2"
    depots = {norm(d) for d in ref.get("depots", [])}

    features, seen = [], set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        if not name:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        key = norm(name)
        if lat is None or key in seen or key in depots or DEPOT.search(name):
            continue
        seen.add(key)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {
                    "name": name,
                    "line": ref_line.get(key),
                    "status": status(tags),
                    "osm_id": f"{el['type']}/{el['id']}",
                },
            }
        )
    features = dedupe(features)
    features.sort(key=lambda f: f["properties"]["name"])

    osm_names = {norm(f["properties"]["name"]) for f in features}
    missing = sorted(n for n in ref_line if n not in osm_names)
    extra = sorted(
        f["properties"]["name"] for f in features if norm(f["properties"]["name"]) not in ref_line
    )
    counts = {}
    for f in features:
        counts[f["properties"]["status"]] = counts.get(f["properties"]["status"], 0) + 1
    print(f"OSM stations: {len(features)} {counts}")
    print(f"Reference operational stations not found in OSM ({len(missing)}): {missing}")
    print(f"OSM stations not in the reference list ({len(extra)}): {extra}")

    if "--write" in sys.argv:
        out = {
            "type": "FeatureCollection",
            "attribution": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
            "fetched": datetime.now(UTC).date().isoformat(),
            "source": "Overpass API; checked against metro_reference.yaml (punemetrorail.org)",
            "features": features,
        }
        (DATA / "metro_stations.geojson").write_text(
            json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8"
        )
        print("wrote", DATA / "metro_stations.geojson")
    return 0


if __name__ == "__main__":
    sys.exit(main())
