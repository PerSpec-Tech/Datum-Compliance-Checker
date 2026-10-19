"""P2.4: evaluator, run on the real rule base and the three fixtures."""

import json

import pytest
from jsonschema import Draft202012Validator

from compliance.config import REPO_ROOT
from compliance.engine.evaluate import evaluate, summarise
from compliance.engine.rules import load_rulebase
from compliance.schemas import registry

RULESETS = ["nbc2016", "udcpr2020", "pmc"]
RESULT_SCHEMA = Draft202012Validator(
    {"$ref": "check-report.schema.json#/definitions/Result"}, registry=registry()
)


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


def run(name, rulebase):
    model = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
    return evaluate(model, rulebase.select(RULESETS), rulebase.tables)


def by_status(results, status):
    return {
        (r["rule_id"], (r["element"] or {}).get("id")) for r in results if r["status"] == status
    }


@pytest.mark.parametrize("name", ["compliant_house", "violating_apartment", "missing_site"])
def test_every_result_matches_the_report_schema(name, rulebase):
    for r in run(name, rulebase):
        RESULT_SCHEMA.validate(r)


def test_compliant_house_has_no_failures_or_gaps(rulebase):
    results = run("compliant_house", rulebase)
    s = summarise(results)
    assert s["fail"] == 0 and s["unverifiable"] == 0, [
        (r["rule_id"], r["message"]) for r in results if r["status"] in ("fail", "unverifiable")
    ]
    assert s["pass"] > 0
    # Not in the TOD zone, so every TOD rule is not applicable.
    assert all(
        r["status"] == "not_applicable" for r in results if r["rule_id"].startswith("pmc.tod")
    )


# (rule, element) → (fix amount, direction, unit)
APARTMENT_FAILS = {
    ("udcpr2020.ch9.stair-width-residential", "ST1"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.stair-riser-max", "ST1"): (0.01, "decrease", "m"),
    ("udcpr2020.ch9.stair-tread-min", "ST1"): (0.01, "increase", "m"),
    ("udcpr2020.ch9.exit-door-width", "D1"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.exit-door-height", "D2"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.habitable-height-min", "S2"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.habitable-height-min", "S4"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.kitchen-height-min", "S3"): (0.05, "increase", "m"),
    ("udcpr2020.ch9.shop-height-min", "S1"): (0.3, "increase", "m"),
    ("pmc.tod.max-fsi", None): (0.7, "decrease", "FSI"),
    ("pmc.tod.mixed-use-road-width", None): (1.5, "increase", "m"),
    ("pmc.tod.tenement-min-carpet", "U1"): (3.0, "increase", "m2"),
    ("pmc.tod.small-tenement-share", None): (0.44, "increase", None),
}


def test_violating_apartment_fails_exactly_the_planted_rules(rulebase):
    results = run("violating_apartment", rulebase)
    assert by_status(results, "fail") == set(APARTMENT_FAILS)
    assert by_status(results, "unverifiable") == set()


def test_violating_apartment_fix_by_amounts(rulebase):
    for r in run("violating_apartment", rulebase):
        if r["status"] != "fail":
            assert r["fix_by"] is None
            continue
        amount, direction, unit = APARTMENT_FAILS[(r["rule_id"], (r["element"] or {}).get("id"))]
        assert r["fix_by"] == {"amount": amount, "unit": unit, "direction": direction}, r["rule_id"]


def test_fail_messages_use_values_and_cite_the_clause(rulebase):
    r = next(x for x in run("violating_apartment", rulebase) if x["rule_id"] == "pmc.tod.max-fsi")
    assert r["message"] == "FSI is 3.20; the TOD maximum for this road width is 2.50."
    assert r["measured"] == pytest.approx(3.2) and r["limit"] == 2.5
    assert r["clause"]["ref"] == "14.2.1.2" and r["clause"]["source"] == "udcpr2020 p.266"
    paths = {f["path"]: f["source"] for f in r["facts_used"]}
    assert paths["project.overlays.metro_tod"] == "declared"
    assert paths["derived.plot_area_m2"] == "declared"
    assert paths["site.edges[e1].road_width_m"] == "declared"  # behind derived.front_road_width_m


def test_element_refs_point_back_to_the_source_model(rulebase):
    r = next(
        x
        for x in run("violating_apartment", rulebase)
        if x["rule_id"] == "udcpr2020.ch9.exit-door-width" and x["status"] == "fail"
    )
    assert r["element"] == {"kind": "doors", "id": "D1", "source_id": "fx-dr-1"}


def test_missing_site_makes_site_rules_unverifiable_not_failed(rulebase):
    results = run("missing_site", rulebase)
    assert by_status(results, "fail") == set()
    unverifiable = {r["rule_id"]: r for r in results if r["status"] == "unverifiable"}
    assert "pmc.tod.max-fsi" in unverifiable
    assert "project.overlays.metro_tod" in unverifiable["pmc.tod.max-fsi"]["missing_inputs"]
    assert unverifiable["pmc.tod.max-fsi"]["message"].startswith("Cannot verify: needs ")
    # Stairs and doors don't depend on the site, so they still pass.
    assert ("udcpr2020.ch9.stair-tread-min", "ST1") in by_status(results, "pass")


def test_results_are_ordered_by_severity_then_rule(rulebase):
    results = run("violating_apartment", rulebase)
    order = {"critical": 0, "major": 1, "minor": 2}
    keys = [(order[r["severity"]], r["rule_id"]) for r in results]
    assert keys == sorted(keys)


# ---------------------------------------------------------------- behaviour with synthetic rules


def _rule(tmp_path, **doc):
    import yaml

    from compliance.engine.rules import load_rulebase as load

    base = {
        "id": "udcpr2020.t.x",
        "title": "Test rule",
        "authority": "udcpr2020",
        "clause": {"ref": "1", "excerpt": "x", "source": "x p.1"},
        "status": "draft",
        "severity": "minor",
        "check": "True",
        "message": "m",
        "compiled_by": "human",
    }
    base.update(doc)
    folder = tmp_path / "rules" / "udcpr2020"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    rb = load(tmp_path / "rules")
    model = json.loads((REPO_ROOT / "fixtures/models/compliant_house.json").read_text("utf-8"))
    return evaluate(model, rb.select(["udcpr2020"]), rb.tables)


def test_expression_error_becomes_unverifiable_with_reason(tmp_path):
    [r] = _rule(tmp_path, check="project.zone + 1 > 0")
    assert r["status"] == "unverifiable"
    assert r["message"].startswith("Could not evaluate this rule:")


def test_non_boolean_check_is_reported(tmp_path):
    [r] = _rule(tmp_path, check="derived.far")
    assert r["status"] == "unverifiable" and "true or false" in r["message"]


def test_advisory_rule_states(tmp_path):
    [r] = _rule(tmp_path, kind="advisory", check="derived.floors_above_ground >= 2")
    assert r["status"] == "advisory"
    [r] = _rule(tmp_path, kind="advisory", check="derived.floors_above_ground >= 9")
    assert r["status"] == "not_applicable"


def test_fix_by_only_for_plain_comparisons(tmp_path):
    [r] = _rule(tmp_path, limit="1.0", measured="derived.far", check="measured * 1 >= limit")
    assert r["status"] == "fail" and r["fix_by"] is None
    [r] = _rule(tmp_path, limit="1.0", measured="derived.far", check="limit <= measured")
    assert r["fix_by"] == {"amount": 0.37, "unit": None, "direction": "increase"}
