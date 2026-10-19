"""P2.5: question planner."""

import json

from jsonschema import Draft202012Validator

from compliance.config import REPO_ROOT
from compliance.engine.evaluate import evaluate
from compliance.engine.questions import plan, question_key
from compliance.engine.rules import load_rulebase
from compliance.schemas import registry

QUESTION_SCHEMA = Draft202012Validator(
    {"$ref": "check-report.schema.json#/definitions/Question"}, registry=registry()
)


def unverifiable(rule_id, *paths):
    return {"rule_id": rule_id, "status": "unverifiable", "missing_inputs": list(paths)}


def test_ranks_by_rules_unlocked():
    qs = plan(
        [
            unverifiable("a", "site.edges[*].road_width_m"),
            unverifiable("b", "site.edges[e1].kind", "project.zone"),
            unverifiable("c", "site.edges"),
            unverifiable("d", "project.zone"),
        ]
    )
    assert [(q["path"], q["unlocks"]) for q in qs] == [("site.edges", 3), ("project.zone", 2)]
    assert qs[0]["input_type"] == "edge_tags" and qs[0]["rule_ids"] == ["a", "b", "c"]


def test_same_rule_on_many_elements_counts_once():
    qs = plan([unverifiable("door-width", f"doors[D{i}].width_m") for i in range(5)])
    assert len(qs) == 1
    q = qs[0]
    assert q["path"] == "doors[*].width_m" and q["unlocks"] == 1
    assert q["prompt"].startswith("5 doors have no 'width_m' in the model")


def test_skips_advisories_table_gaps_and_other_statuses():
    qs = plan(
        [
            unverifiable("fire", "project.zone"),
            unverifiable("tbl", "table:pmc.tod_max_fsi[7.0]"),
            {"rule_id": "x", "status": "fail", "missing_inputs": ["project.zone"]},
        ],
        advisory_rule_ids={"fire"},
    )
    assert qs == []


def test_enum_questions_list_options_from_the_schema():
    [q] = plan([unverifiable("t", "project.building_type")])
    assert q["input_type"] == "enum" and "bungalow_self_use" in q["options"]


def test_question_keys():
    assert question_key("site.edges[e2].road_width_m") == "site.edges"
    assert question_key("project.occupancy.subdivision") == "project.occupancy"
    assert question_key("units[U3].carpet_area_m2") == "units[*].carpet_area_m2"
    assert question_key("table:x[1]") is None


def test_missing_site_fixture_asks_about_tod_and_road_edges():
    rb = load_rulebase()
    model = json.loads((REPO_ROOT / "fixtures/models/missing_site.json").read_text("utf-8"))
    results = evaluate(model, rb.select(["nbc2016", "udcpr2020", "pmc"]), rb.tables)
    advisory = {r.id for r in rb.rules.values() if r.kind == "advisory"}
    qs = plan(results, advisory)
    for q in qs:
        QUESTION_SCHEMA.validate(q)
    paths = [q["path"] for q in qs]
    # With batch-1 rules, every TOD rule waits on the TOD answer, so it ranks first; the road
    # edges question unlocks the TOD FSI rule. Margin/FSI rules (P2.6 batch 2) will add to it.
    assert paths[0] == "project.overlays.metro_tod"
    assert "site.edges" in paths
    # 3, not 5: mixed-use and small-tenement rules are already not_applicable for a bungalow
    # ("False and <missing>" is False), so the TOD answer can't change them.
    assert qs[0]["unlocks"] == 3
