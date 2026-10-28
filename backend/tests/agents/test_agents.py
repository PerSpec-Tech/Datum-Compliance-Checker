"""The agents with a fake LLM and a fake Tavily (no tokens or credits spent)."""

import copy
import json
from types import SimpleNamespace

import pytest

from compliance.agents import classify, explain, freshness, questions_text
from compliance.config import REPO_ROOT
from compliance.engine.report import build_report
from compliance.engine.rules import load_rulebase
from compliance.llm.client import ChatResult
from compliance.search.tavily import Search
from compliance.store.db import Database
from compliance.store.repo import Store


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def chat(self, role, messages, **kw):
        self.calls.append((role, messages, kw))
        a = self.answers.pop(0)
        data = a(messages) if callable(a) else a
        return ChatResult(content=json.dumps(data), data=data, model="fake")


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


@pytest.fixture
def store(tmp_path):
    return Store(Database(tmp_path / "t.sqlite"))


def model(name="compliant_house"):
    return json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))


# ------------------------------------------------------------------ classify


def test_classify_fills_unknown_rooms_only():
    m = model()
    m["spaces"][0]["usage"] = {"value": None, "source": "default"}  # Living → unknown
    m["spaces"][1]["usage"] = {"value": None, "source": "default"}  # Kitchen → unknown
    m["spaces"][2]["usage"] = {"value": "bathroom", "source": "declared"}
    llm = FakeLLM({"rooms": [
        {"id": "S1", "usage": "living", "confidence": 0.95},
        {"id": "S2", "usage": "kitchen", "confidence": 0.4},   # too unsure → stays unknown
        {"id": "S99", "usage": "office", "confidence": 0.99},  # not sent → ignored
    ]})  # fmt: skip
    msg = classify.classify_spaces(m, llm)
    assert (
        m["spaces"][0]["usage"]["value"] == "living"
        and m["spaces"][0]["usage"]["source"] == "inferred"
    )
    assert m["spaces"][1]["usage"]["value"] is None
    assert m["spaces"][2]["usage"] == {"value": "bathroom", "source": "declared"}
    assert "1 room" in msg and "1 left" in msg
    sent = llm.calls[0][1][1]["content"]
    assert 'S1: "Living"' in sent and "S3" not in sent  # declared room never sent


def test_classify_skips_when_nothing_to_do():
    assert classify.classify_spaces(model(), FakeLLM()) is None


# ------------------------------------------------------------------ explain


def apartment_report(rulebase):
    return build_report(model("violating_apartment"), rulebase, project_id="p", model_version="v")


def test_explain_builds_summary_and_drops_unknown_failures(rulebase):
    report = apartment_report(rulebase)
    llm = FakeLLM({
        "summary": "13 checks fail. FSI 3.20 is over the TOD maximum of 2.50.",
        "failures": [
            {"rule_id": "pmc.tod.max-fsi", "element_id": None,
             "explanation": "Reduce built-up area."},
            {"rule_id": "made.up.rule", "element_id": None, "explanation": "Invented."},
        ],
    })  # fmt: skip
    text = explain.explain(report, llm)
    assert text.startswith("13 checks fail.")
    assert "• Maximum total FSI in the TOD zone: Reduce built-up area." in text
    assert "Invented" not in text
    assert llm.calls[0][0] == "agent"


def test_explain_regenerates_then_strips_invented_clause_refs(rulebase):
    report = apartment_report(rulebase)
    bad = {"summary": "Fails 9.29.1. Also see Regulation 99.9.9 for parking.", "failures": []}
    llm = FakeLLM(bad, bad)
    text = explain.explain(report, llm)
    assert "99.9.9" not in text and "Fails 9.29.1." in text
    assert len(llm.calls) == 2  # one regeneration attempt


# ------------------------------------------------------------------ questions


QS = [
    {"path": "site.edges", "prompt": "Which sides face a road?", "unlocks": 7},
    {"path": "project.zone", "prompt": "Zone?", "unlocks": 2},
]


def test_reword_keeps_order_and_paths():
    qs = copy.deepcopy(QS)
    llm = FakeLLM({"questions": [
        {"path": "site.edges",
         "prompt": "Which plot edges face a road, and how wide is each (DP width)?"},
        {"path": "project.zone", "prompt": "Which Development Plan zone is the plot in?"},
    ]})  # fmt: skip
    assert questions_text.reword(qs, llm) == 2
    assert qs[0]["prompt"].startswith("Which plot edges") and qs[0]["unlocks"] == 7


def test_reword_rejects_reordered_answers():
    qs = copy.deepcopy(QS)
    llm = FakeLLM(
        {
            "questions": [
                {"path": "project.zone", "prompt": "Zone please"},
                {"path": "site.edges", "prompt": "x" * 20},
            ]
        }
    )
    assert questions_text.reword(qs, llm) == 0 and qs == QS


# ------------------------------------------------------------------ Tavily client


class FakeTavily:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    def search(self, **kw):
        self.calls += 1
        self.kw = kw
        return {"results": self.results}

    def extract(self, urls):
        self.calls += 1
        return {"results": [{"url": urls[0], "raw_content": "x" * 70_000}]}


def test_search_uses_authority_domains_caches_and_logs(store):
    fake = FakeTavily([{"url": "https://pmc.gov.in/a", "title": "A", "content": "c", "score": 0.9}])
    s = Search(store, client_factory=lambda: fake)
    r1 = s.search("TOD notification", authority_id="pmc")
    r2 = s.search("TOD notification", authority_id="pmc")
    assert r1 == r2 and fake.calls == 1
    assert "pmc.gov.in" in fake.kw["include_domains"]
    assert store.usage_summary()["search"] == [{"kind": "search", "calls": 2, "live_calls": 1}]
    assert len(s.extract("https://pmc.gov.in/x.pdf")) == 60_000


# ------------------------------------------------------------------ freshness


def test_freshness_flags_only_with_a_real_url_and_caches(rulebase, store):
    report = apartment_report(rulebase)
    hits = [
        {
            "url": "https://urban.maharashtra.gov.in/tod-amendment.pdf",
            "title": "Modification to 14.2.1",
            "content": "…",
            "score": 1,
        }
    ]
    fake = FakeTavily(hits)
    search = Search(store, client_factory=lambda: fake)

    def verdict(messages):
        rule = messages[0]["content"]
        if "14.2.1.2" in rule:
            return {
                "status": "possibly_superseded",
                "url": hits[0]["url"],
                "reason": "TOD modification",
            }
        if "9.29.1" in rule:
            return {
                "status": "possibly_superseded",
                "url": "https://invented.example",
                "reason": "hallucinated",
            }
        return {"status": "current", "url": None, "reason": "no change"}

    llm = FakeLLM(*[verdict] * 6)
    msg = freshness.apply_to_report(report, rulebase.rules, "pmc", search, llm, store)
    by_rule = {r["rule_id"]: r["freshness"] for r in report["results"] if r["status"] == "fail"}
    assert by_rule["pmc.tod.max-fsi"]["status"] == "possibly_superseded"
    assert by_rule["pmc.tod.max-fsi"]["url"] == hits[0]["url"]
    assert by_rule["udcpr2020.ch9.exit-door-width"]["status"] == "current"  # invented URL rejected
    # At most 6 regulations per check, most severe first: a major rule further down stays unchecked.
    assert by_rule["udcpr2020.ch9.stair-riser-max"]["status"] == "unchecked"
    assert "Tavily checked 6 regulations" in msg
    # Second run: verdicts come from the cache (no new LLM calls).
    llm2 = FakeLLM()
    freshness.apply_to_report(
        apartment_report(rulebase), rulebase.rules, "pmc", search, llm2, store
    )
    assert llm2.calls == []


def test_hooks_assemble_when_keys_present(store, monkeypatch):
    from compliance.agents import hooks

    monkeypatch.setattr(
        hooks, "get_settings", lambda: SimpleNamespace(nebius_api_key="k", tavily_api_key="t")
    )
    assert set(hooks.make_hooks(store, llm=FakeLLM(), search=Search(store, lambda: None))) == {
        "classify_usage",
        "explain",
        "freshness",
    }
    monkeypatch.setattr(
        hooks, "get_settings", lambda: SimpleNamespace(nebius_api_key="", tavily_api_key="")
    )
    assert hooks.make_hooks(store) == {}
