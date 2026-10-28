"""SQLite store."""

import json
from datetime import timedelta

import pytest

from compliance.config import REPO_ROOT
from compliance.store.db import Database
from compliance.store.repo import Store


@pytest.fixture
def store(tmp_path):
    return Store(Database(tmp_path / "t.sqlite"))


def fixture_model():
    return json.loads((REPO_ROOT / "fixtures/models/compliant_house.json").read_text("utf-8"))


def test_migrate_is_idempotent(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    db.migrate()
    db.migrate()
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "projects",
        "model_versions",
        "briefs",
        "jobs",
        "reports",
        "llm_usage",
        "search_usage",
        "tavily_cache",
        "pair_codes",
        "tokens",
    } <= tables


def test_projects_models_and_latest(store):
    pid = store.create_project("House")
    assert store.get_project(pid)["name"] == "House"
    v1 = store.add_model_version(pid, fixture_model())
    v2 = store.add_model_version(pid, fixture_model())
    latest_id, model = store.latest_model(pid)
    assert latest_id == v2 != v1
    assert model["schema_version"] == "1.0"
    assert store.latest_model("nope") is None


def test_brief_answers_are_declared_and_upserted(store):
    pid = store.create_project("P")
    store.set_brief(pid, {"site.edges[e1].road_width_m": 9.0, "project.zone": "residential"})
    store.set_brief(pid, {"site.edges[e1].road_width_m": 12.0})
    brief = store.get_brief(pid)
    assert brief["site.edges[e1].road_width_m"] == {"value": 12.0, "source": "declared"}
    assert brief["project.zone"]["value"] == "residential"


def test_jobs_and_reports(store):
    pid = store.create_project("P")
    vid = store.add_model_version(pid, fixture_model())
    jid = store.create_job(pid, vid)
    assert store.get_job(jid)["status"] == "queued"
    store.update_job(jid, status="running", stage="evaluate", pct=40, bogus="ignored")
    job = store.get_job(jid)
    assert (job["status"], job["stage"], job["pct"]) == ("running", "evaluate", 40)
    report = {
        "id": "r1",
        "project_id": pid,
        "model_version": vid,
        "created_at": "2026-10-20T00:00:00+00:00",
        "x": 1,
    }
    store.save_report(report)
    assert store.get_report("r1") == report


def test_usage_summary(store):
    store.record_llm_usage(
        role="agent",
        model="m-super",
        ok=True,
        prompt_tokens=100,
        completion_tokens=20,
        latency_ms=900,
    )
    store.record_llm_usage(role="agent", model="m-super", ok=False, latency_ms=100)
    store.record_search(kind="search", query="q", cached=False, results=5)
    store.record_search(kind="search", query="q", cached=True, results=5)
    s = store.usage_summary()
    [m] = s["models"]
    assert (m["calls"], m["ok_calls"], m["prompt_tokens"], m["completion_tokens"]) == (
        2,
        1,
        100,
        20,
    )
    assert s["search"] == [{"kind": "search", "calls": 2, "live_calls": 1}]


def test_cache_respects_max_age(store):
    store.cache_put("k", "search", {"q": 1}, {"results": [1]})
    assert store.cache_get("k", timedelta(days=7)) == {"results": [1]}
    assert store.cache_get("k", timedelta(seconds=-1)) is None
    assert store.cache_get("missing", timedelta(days=7)) is None


def test_pairing_code_is_single_use_and_token_is_hashed(store):
    code = store.create_pair_code()
    assert len(code) == 6 and code.isdigit()
    token = store.consume_pair_code(code, "PC-1")
    assert token and store.check_token(token)
    assert store.consume_pair_code(code, "PC-2") is None  # used
    assert not store.check_token("wrong")
    assert store.db.one("SELECT COUNT(*) AS n FROM tokens WHERE token_hash = ?", (token,))["n"] == 0


def test_expired_code_is_rejected(store):
    code = store.create_pair_code()
    store.db.execute(
        "UPDATE pair_codes SET expires_at = '2000-01-01T00:00:00+00:00' WHERE code = ?", (code,)
    )
    assert store.consume_pair_code(code, None) is None
