"""Planning-fact suggestions (P12.1): building type, occupancy, congested area, land use."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx

from compliance.adapters import dxf
from compliance.agents import planning
from compliance.store.db import Database
from compliance.store.repo import Store

REPO_ROOT = Path(__file__).resolve().parents[3]


def _model(name: str) -> dict:
    return dxf.read(REPO_ROOT / "fixtures" / "dxf" / f"{name}.dxf")[0]


def test_house_is_a_one_family_dwelling():
    s = planning.building(_model("demo_house"))
    assert s["project.occupancy"]["value"] == {"group": "A", "subdivision": "A-2"}
    assert s["project.building_type"]["value"] == "bungalow_self_use"
    assert all(f["source"] == "inferred" for f in s.values())


def test_shops_with_flats_are_mixed_use_apartments():
    s = planning.building(_model("demo_apartment"))
    assert s["project.occupancy"]["value"] == {"group": "A", "subdivision": "A-4"}
    assert s["project.building_type"]["value"] == "mixed_use"
    assert "3.1.1.2" in s["project.building_type"]["note"]


def test_shops_only_is_mercantile():
    m = _model("demo_apartment")
    m["units"] = [u for u in m["units"] if u["use"]["value"] != "residential"]
    m["spaces"] = [s for s in m["spaces"] if s["usage"]["value"] != "kitchen"]
    s = planning.building(m)
    assert s["project.occupancy"]["value"]["group"] in ("E", "F")
    assert s["project.building_type"]["value"] == "other"


def test_congested_from_locality():
    assert planning.congested("Kasba Peth", "pmc")["value"] is True
    assert planning.congested("Erandwane", "pmc")["value"] is False
    assert planning.congested(None, "pmc") is None
    assert planning.congested("Kasba Peth", "nowhere") is None


def test_apply_never_overrides_model_or_declared():
    m = _model("demo_house")
    m["project"]["congested_area"] = {"value": True, "source": "declared", "note": None}
    m["project"]["building_type"] = {"value": "standalone", "source": "model", "note": None}
    before = copy.deepcopy(m["project"])
    msg = planning.apply(m, {"locality": "Erandwane", "landuse": "residential"})
    p = m["project"]
    assert p["congested_area"] == before["congested_area"]
    assert p["building_type"] == before["building_type"]
    assert p["occupancy"]["value"]["subdivision"] == "A-2"  # replaced the layer-based guess
    assert p["zone"]["value"] == "residential" and "not the DP zone" in p["zone"]["note"]
    assert "occupancy A-2" in msg


def _fake(calls: list[str]) -> httpx.Client:
    def handle(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if "nominatim" in req.url.host:
            address = {"suburb": "Shaniwar Peth", "city": "Pune"}
            return httpx.Response(200, json={"address": address})
        if "overpass-api.de" in req.url.host:
            return httpx.Response(502)  # the main server is busy: the mirror answers
        tags = [{"amenity": "school"}, {"landuse": "residential", "name": "Peth"}]
        body = {"elements": [{"tags": t} for t in tags]}
        return httpx.Response(200, content=json.dumps(body))

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_lookup_uses_the_mirror_and_caches(tmp_path):
    st = Store(Database(tmp_path / "t.sqlite"))
    calls: list[str] = []
    site = planning.lookup(18.5167, 73.8562, st, _fake(calls))
    assert site == {"locality": "Shaniwar Peth", "landuse": "residential", "landuse_name": "Peth"}
    assert calls.count("overpass-api.de") == 1 and len(calls) == 3
    calls.clear()
    assert planning.lookup(18.5167, 73.8562, st, _fake(calls)) == site
    assert calls == []  # both from the cache


def test_cached_only_never_calls_overpass(tmp_path):
    calls: list[str] = []
    st = Store(Database(tmp_path / "t.sqlite"))
    site = planning.lookup(18.5, 73.8, st, _fake(calls), cached_only=True)
    assert site["landuse"] is None and site["locality"] == "Shaniwar Peth"
    assert not any("overpass" in c for c in calls)
