"""metro TOD overlay."""

import copy
import json

import pytest

from compliance.agents import overlays
from compliance.agents.overlays import apply_overlays, distance_m
from compliance.config import REPO_ROOT
from compliance.engine.rules import load_rulebase

# Synthetic stations around a point in Pune; ~0.009° latitude ≈ 1 km.
STATIONS = [
    {"name": "Alpha", "line": "1", "status": "operational", "lat": 18.5000, "lon": 73.8500},
    {"name": "Beta", "line": None, "status": "proposed", "lat": 18.4000, "lon": 73.8500},
]


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(overlays, "stations", lambda authority: STATIONS)
    m = json.loads((REPO_ROOT / "fixtures/models/compliant_house.json").read_text("utf-8"))
    m["project"]["overlays"]["metro_tod"] = {"value": None, "source": "default"}
    return m


def at(m, lat, lon):
    m = copy.deepcopy(m)
    m["project"]["location"] = {"value": {"lat": lat, "lon": lon}, "source": "declared"}
    return m


def offset(metres):
    return 18.5000 + metres / 111_195.0  # metres north of Alpha


def test_distance_is_haversine():
    assert distance_m(18.5, 73.85, offset(500), 73.85) == pytest.approx(500, abs=1)


def test_near_a_station_is_in_the_zone(model, rulebase):
    m = at(model, offset(300), 73.85)
    msg = apply_overlays(m, rulebase)
    o = m["project"]["overlays"]
    assert o["metro_tod"]["value"] is True and o["metro_tod"]["source"] == "inferred"
    assert o["nearest_metro_station"]["value"]["name"] == "Alpha"
    assert o["nearest_metro_station"]["value"]["distance_m"] == pytest.approx(300, abs=1)
    assert "inside the TOD zone" in msg


def test_far_from_any_station_is_outside(model, rulebase):
    m = at(model, offset(2000), 73.85)
    apply_overlays(m, rulebase)
    assert m["project"]["overlays"]["metro_tod"]["value"] is False


def test_boundary_band_becomes_a_question(model, rulebase):
    m = at(model, offset(540), 73.85)  # 500–575 m: can't tell from a station point
    msg = apply_overlays(m, rulebase)
    tod = m["project"]["overlays"]["metro_tod"]
    assert tod["value"] is None and tod["source"] == "default"
    assert "question added" in msg


def test_proposed_station_nearby_asks_instead_of_guessing(model, rulebase):
    m = at(model, 18.4005, 73.85)  # ~55 m from proposed Beta, ~11 km from Alpha
    apply_overlays(m, rulebase)
    assert m["project"]["overlays"]["metro_tod"]["value"] is None


def test_declared_value_is_never_changed(model, rulebase):
    m = at(model, offset(2000), 73.85)
    m["project"]["overlays"]["metro_tod"] = {"value": True, "source": "declared"}
    msg = apply_overlays(m, rulebase)
    assert m["project"]["overlays"]["metro_tod"] == {"value": True, "source": "declared"}
    assert "as declared" in msg


def test_real_station_data_is_present():
    real = overlays.stations.__wrapped__("pmc")
    assert len(real) > 60
    assert {"Deccan Gymkhana", "PMC Bhavan", "Swargate"} <= {s["name"] for s in real}
