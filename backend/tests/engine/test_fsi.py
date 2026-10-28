"""FSI headroom summary, on the fixtures and the real rule base."""

import json

import pytest
from jsonschema import Draft202012Validator

from compliance.config import REPO_ROOT
from compliance.engine.derived import compute
from compliance.engine.evaluate import evaluate
from compliance.engine.fsi import fsi_summary
from compliance.engine.rules import load_rulebase
from compliance.schemas import registry

SCHEMA = Draft202012Validator(
    {"$ref": "check-report.schema.json#/definitions/FsiSummary"}, registry=registry()
)


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


def summary(name, rulebase, mutate=None):
    model = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
    if mutate:
        mutate(model)
    derived = compute(model)
    results = evaluate(
        model, rulebase.select(["nbc2016", "udcpr2020", "pmc"]), rulebase.tables, derived
    )
    s = fsi_summary(results, rulebase.rules, derived)
    SCHEMA.validate(s)
    return s


def test_tod_apartment_inside_zone_12m_band(rulebase):
    # Make the road 12 m: TOD table band 12–15 m → 3.00.
    def road_12(m):
        m["site"]["edges"][0]["road_width_m"]["value"] = 12.0

    s = summary("violating_apartment", rulebase, road_12)
    assert s["used"] == pytest.approx(3.2)
    assert s["base_permissible"] == 1.1
    assert s["max_permissible"] == 3.0
    assert s["headroom_base_m2"] == pytest.approx(-2100.0)
    assert s["headroom_max_m2"] == pytest.approx(-200.0)  # 200 m² over the TOD maximum
    assert any("14.2.1.2" in b for b in s["basis"])


def test_outside_tod_uses_table_6g(rulebase):
    s = summary("compliant_house", rulebase)  # 9 m road, non-congested, not TOD
    assert s["used"] == pytest.approx(0.63)
    assert s["base_permissible"] == 1.1
    assert s["max_permissible"] == 2.0  # Table 6-G, 9–12 m road
    assert s["headroom_base_m2"] == pytest.approx(141.0)  # (1.10 − 0.63) × 300
    assert s["headroom_max_m2"] == pytest.approx(411.0)  # (2.00 − 0.63) × 300
    assert "pmc.tod.max-fsi" in s["rule_ids"]


def test_missing_road_width_gives_nulls_and_inputs(rulebase):
    s = summary("missing_site", rulebase)
    assert s["used"] is None and s["max_permissible"] is None
    assert s["headroom_base_m2"] is None and s["headroom_max_m2"] is None
    assert "site.plot_area_declared_m2" in s["missing_inputs"]
    assert any(p.startswith("site.edges") for p in s["missing_inputs"])
