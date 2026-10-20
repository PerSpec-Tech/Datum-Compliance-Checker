"""P3.5: rule compiler — the deterministic checks and the retry / review loop (fake LLM)."""

import json

import pytest

from compliance.agents import compiler
from compliance.agents.compiler import Clause, compile_clause, validate
from compliance.engine.catalog import catalog
from compliance.engine.rules import load_rulebase
from compliance.llm.client import ChatResult

CLAUSE = Clause(
    "Doorways for the bathrooms, water-closets or stores shall be not less than 75 cm. wide.",
    "9.29.1 (ii)",
    "udcpr2020 p.165",
    "udcpr2020",
)
GOOD = {
    "slug": "wet-room-door-width",
    "title": "Minimum door width for bathrooms, WCs and stores",
    "severity": "minor",
    "kind": "check",
    "for_each": "doors",
    "applies_when": "spaces[item.to_space_id].usage in ['bathroom', 'wc', 'storage']",
    "limit": "0.75",
    "measured": "item.width_m",
    "check": "measured >= limit",
    "message": "Door is {measured:.2f} m wide; minimum is {limit:.2f} m.",
    "fix_unit": "m",
    "new_tables": [],
    "notes": "",
}


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def chat(self, role, messages, **kw):
        self.calls.append((role, messages))
        data = self.answers.pop(0)
        return ChatResult(content=json.dumps(data), data=data, model="fake")


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


def docs(draft):
    return compiler._documents(draft, CLAUSE)


def test_good_draft_passes_every_check(rulebase):
    rule, tables = docs(GOOD)
    errs, dry = validate(rule, tables, rulebase, CLAUSE.text)
    assert errs == []
    assert rule["id"] == "udcpr2020.draft.wet-room-door-width"
    assert rule["status"] == "draft" and rule["clause"]["ref"] == "9.29.1 (ii)"
    assert set(dry) == {"compliant_house", "violating_apartment", "missing_site"}


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"limit": "0.8"}, "the number 0.8 does not appear in the clause text"),
        ({"measured": "item.clear_width_m"}, "reads 'item.clear_width_m', which doesn't exist"),
        ({"check": "measured >= limit and item.__class__"}, "not allowed"),
        ({"message": "Door {item.width_m}"}, "message may only use"),
        ({"for_each": None}, "uses 'item' but the rule has no for_each"),
        ({"check": "measured"}, "dry run"),  # not a boolean: evaluation error on the fixtures
        ({"slug": "Bad Slug"}, "does not match"),
    ],
)
def test_bad_drafts_are_caught(rulebase, change, error):
    rule, tables = docs({**GOOD, **change})
    errs, _ = validate(rule, tables, rulebase, CLAUSE.text)
    assert any(error in e for e in errs), errs


def test_unit_conversions_count_as_from_the_clause():
    allowed = compiler._clause_numbers("not less than 90 cm. and 200 cm. in height; 50% of FSI")
    assert {90.0, 0.9, 2.0, 0.5} <= allowed


def test_new_tables_are_checked_too(rulebase):
    draft = {
        **GOOD,
        "limit": "table('udcpr2020.wet_door', 'default')",
        "new_tables": [{"name": "wet_door", "description": "d", "unit": "m", "kind": "map",
                        "map": {"default": 0.7}, "bands": None}],
    }  # fmt: skip
    rule, tables = docs(draft)
    errs, _ = validate(rule, tables, rulebase, CLAUSE.text)
    assert any("0.7 does not appear" in e for e in errs)


def test_retry_feeds_errors_back_then_succeeds(rulebase):
    llm = FakeLLM({**GOOD, "limit": "0.8"}, GOOD)
    result = compile_clause(CLAUSE, llm, rulebase)
    assert result.ok and result.attempts == 2
    feedback = llm.calls[1][1][-1]["content"]
    assert "0.8 does not appear" in feedback


def test_gives_up_after_retries(rulebase):
    bad = {**GOOD, "limit": "0.8"}
    result = compile_clause(CLAUSE, FakeLLM(bad, bad, bad), rulebase)
    assert not result.ok and result.attempts == 3 and result.errors


def test_review_issues_trigger_one_revision(rulebase):
    weak = {**GOOD, "applies_when": None}
    llm = FakeLLM(
        weak,
        {"verdict": "issues", "notes": ["applies to every door, not only wet rooms"]},
        GOOD,
        {"verdict": "faithful", "notes": []},
    )
    result = compile_clause(CLAUSE, llm, rulebase, review=True)
    assert result.ok and result.review["verdict"] == "faithful"
    assert result.review_history[0]["verdict"] == "issues"
    assert [role for role, _ in llm.calls] == ["agent", "reviewer", "agent", "reviewer"]
    assert "applies to every door" in llm.calls[2][1][-1]["content"]


def test_catalog_lists_room_length_and_rejects_unknown_fields():
    c = catalog()
    assert "derived.space_min_length_m" in c.derived
    assert c.known("item.width_m", "doors") and not c.known("item.width_m", None)


def test_saved_drafts_load_with_their_tables():
    rb = load_rulebase(include_drafts=True)
    drafts = [r for r in rb.rules.values() if ".draft." in r.id]
    assert all(r.doc["status"] == "draft" for r in drafts)
    assert "udcpr2020.draft.wet-room-door-width" not in rb.rules  # tests never write drafts
