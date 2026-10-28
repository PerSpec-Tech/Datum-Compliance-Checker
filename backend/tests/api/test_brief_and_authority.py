"""Brief merge and authority resolver (location part)."""

import json

import httpx
import pytest

from compliance.agents import authority
from compliance.config import REPO_ROOT
from compliance.engine.brief import apply_brief
from compliance.store.db import Database
from compliance.store.repo import Store


def model():
    return json.loads((REPO_ROOT / "fixtures/models/missing_site.json").read_text("utf-8"))


def D(v):
    return {"value": v, "source": "declared"}


def test_plot_drawn_on_the_map_replaces_the_boundary_and_sides():
    ring = [[0, 0], [20, 0], [20, 30], [0, 30], [0, 0]]
    merged, skipped = apply_brief(
        model(),
        {
            "site.edges": D({"e1": {"kind": "road", "road_width_m": 12}}),  # tags the new e1
            "site.boundary": D(ring),
            "site.placement": D({"lat": 18.5, "lon": 73.8, "rotation_deg": 0, "scale": 1}),
        },
    )
    assert skipped == []
    site = merged["site"]
    assert site["boundary"] == ring[:-1]
    assert [e["id"] for e in site["edges"]] == ["e1", "e2", "e3", "e4"]
    assert site["edges"][0]["kind"]["value"] == "road"
    assert site["edges"][1]["kind"]["source"] == "default"
    assert apply_brief(model(), {"site.boundary": D([[0, 0], [1, 1]])})[1] == ["site.boundary"]


def test_apply_brief_sets_declared_facts_and_skips_stale_paths():
    m = json.loads((REPO_ROOT / "fixtures/models/compliant_house.json").read_text("utf-8"))
    merged, skipped = apply_brief(
        m,
        {
            "site.edges[e2].kind": D("road"),
            "site.edges[e9].kind": D("road"),  # no such edge
            "project.zone": D("commercial"),
            "spaces[S1].usage": D("office"),
            "site.ground_level_m": D(1.0),  # a measured value, not a fact: refused
            "nonsense.path": D(1),
        },
    )
    assert merged["site"]["edges"][1]["kind"] == {"value": "road", "source": "declared"}
    assert merged["project"]["zone"]["value"] == "commercial"
    assert merged["spaces"][0]["usage"]["value"] == "office"
    assert merged["site"]["ground_level_m"] == 0.0
    assert set(skipped) == {"site.edges[e9].kind", "site.ground_level_m", "nonsense.path"}
    assert m["project"]["zone"]["value"] == "residential"  # input untouched


def test_apply_brief_grouped_edge_tags():
    m = json.loads((REPO_ROOT / "fixtures/models/compliant_house.json").read_text("utf-8"))
    merged, skipped = apply_brief(
        m,
        {
            "site.edges": D(
                {"e3": {"kind": "road", "road_width_m": 12, "road_width_basis": "existing"}}
            )
        },
    )
    e3 = merged["site"]["edges"][2]
    assert (e3["kind"]["value"], e3["road_width_m"]["value"], e3["road_width_basis"]["value"]) == (
        "road",
        12,
        "existing",
    )
    assert skipped == []


def nominatim(address, calls):
    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"address": address})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolves_pune_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(authority.time, "sleep", lambda s: None)
    store = Store(Database(tmp_path / "t.sqlite"))
    calls = []
    http = nominatim({"city": "Pune", "state": "Maharashtra", "country": "India"}, calls)
    r = authority.resolve(18.5165, 73.842, store, http)
    assert (r.authority_id, r.rulesets) == ("pmc", ["nbc2016", "udcpr2020", "pmc"])
    authority.resolve(18.5165, 73.842, store, http)
    assert len(calls) == 1  # second lookup came from the cache


def test_pimpri_chinchwad_is_not_pmc(monkeypatch):
    monkeypatch.setattr(authority.time, "sleep", lambda s: None)
    r = authority.resolve(
        18.62, 73.80, None, nominatim({"city": "Pimpri-Chinchwad", "state": "Maharashtra"}, [])
    )
    assert r.rulesets is None and "Pimpri-Chinchwad is not covered yet" in r.note


def test_offline_falls_back_to_the_area_box(monkeypatch):
    monkeypatch.setattr(authority.time, "sleep", lambda s: None)

    def down(request):
        raise httpx.ConnectError("offline", request=request)

    http = httpx.Client(transport=httpx.MockTransport(down))
    r = authority.resolve(18.52, 73.85, None, http)
    assert r.authority_id == "pmc" and "offline area box" in r.note
    assert authority.resolve(41.88, -87.63, None, http).rulesets is None


def test_search_is_bounded_to_the_authority_and_cached(tmp_path, monkeypatch):
    import httpx
    import pytest

    from compliance.agents import authority
    from compliance.store.db import Database
    from compliance.store.repo import Store

    monkeypatch.setattr(authority, "_throttle", lambda: None)
    seen = []

    def handler(request):
        seen.append(request.url.params)
        return httpx.Response(200, json=[{"display_name": "Kothrud, Pune", "lat": "18.5074",
                                          "lon": "73.8077"}])  # fmt: skip

    http = httpx.Client(transport=httpx.MockTransport(handler))
    st = Store(Database(tmp_path / "g.sqlite"))
    places = authority.search("  Kothrud  ", "pmc", st, http)
    assert places == [{"label": "Kothrud, Pune", "lat": 18.5074, "lon": 73.8077}]
    assert seen[0]["bounded"] == "1" and seen[0]["viewbox"] == "73.74,18.64,73.98,18.42"
    assert authority.search("kothrud", "pmc", st, http) == places and len(seen) == 1  # cached
    with pytest.raises(ValueError):
        authority.search("x", "nowhere", st, http)


def test_bund_garden_resolves_to_pmc_at_street_level(monkeypatch):
    """Regression: at town zoom Nominatim said "Khadki" for Bund Garden, which is inside PMC."""
    import httpx

    from compliance.agents import authority

    monkeypatch.setattr(authority, "_throttle", lambda: None)
    zooms = []

    def handler(request):
        zooms.append(request.url.params["zoom"])
        address = {"suburb": "Ghorpuri", "city": "Pune", "state": "Maharashtra"}
        return httpx.Response(200, json={"address": address})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    r = authority.resolve(18.53779, 73.88918, None, http)
    assert r.authority_id == "pmc" and zooms == ["18"]


@pytest.mark.parametrize(
    ("address", "pmc"),
    [
        ({"suburb": "Kondhwa", "village": "Kondhwa Budruk", "county": "Pune City Subdistrict",
          "state": "Maharashtra"}, True),  # merged village: no city in OSM, still PMC
        ({"suburb": "Mandalay Lines", "town": "Khadki", "county": "Pune City Subdistrict",
          "state": "Maharashtra"}, False),  # cantonment board
        ({"city": "Pimpri-Chinchwad", "county": "Haveli", "state": "Maharashtra"}, False),
        ({"city": "Pune", "suburb": "Kasba Peth", "state": "Maharashtra"}, True),
    ],
)  # fmt: skip
def test_pmc_limits_from_street_level_addresses(address, pmc):
    from compliance.agents.authority import _matches, authorities

    assert _matches(next(a for a in authorities() if a["id"] == "pmc"), address) is pmc
