"""P4.2–P4.4: the HTTP API, end to end, as the Revit add-in and the web app use it."""

import json

import pytest
from fastapi.testclient import TestClient

from compliance.agents.authority import Resolution
from compliance.config import REPO_ROOT
from compliance.jobs import JobRunner
from compliance.main import create_app

PMC = Resolution("pmc", ["nbc2016", "udcpr2020", "pmc"], "Pune Municipal Corporation (test)")


def fixture(name):
    return json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))


@pytest.fixture
def client(tmp_path):
    calls = []

    def resolver(lat, lon, store=None):
        calls.append((lat, lon))
        return PMC if 18 < lat < 19 else Resolution(None, None, "Chicago is not covered yet")

    app = create_app(
        tmp_path / "api.sqlite", runner_factory=lambda s, rb: JobRunner(s, rb, resolver=resolver)
    )
    with TestClient(app) as c:
        c.resolver_calls = calls
        yield c


def pair(client):
    code = client.post("/api/pair/start").json()["code"]
    token = client.post("/api/pair/complete", json={"code": code, "device": "TEST-PC"}).json()[
        "token"
    ]
    return {"Authorization": f"Bearer {token}"}


def run_check(client, project_id):
    job_id = client.post(f"/api/projects/{project_id}/checks").json()["job_id"]
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return job_id, events


def test_revit_round_trip(client):
    auth = pair(client)
    pid = client.post("/api/projects", json={"name": "Apartment"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/model", json=fixture("violating_apartment"), headers=auth)
    assert r.status_code == 200 and r.json()["model_version"]

    job_id, events = run_check(client, pid)
    stages = [e["stage"] for e in events]
    assert stages[0] == "resolve_authority" and stages[-1] == "done"
    assert {"evaluate", "freshness", "plan_questions", "explain"} <= set(stages)
    pcts = [e["pct"] for e in events]
    assert pcts == sorted(pcts)

    report = client.get(f"/api/reports/{events[-1]['report_id']}").json()
    assert report["summary"]["fail"] == 13
    assert report["project_id"] == pid
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    project = client.get(f"/api/projects/{pid}").json()
    assert project["latest_report_id"] == report["id"]
    assert client.resolver_calls == []  # the fixture already knows its rule sets


def test_events_replay_after_the_job_finished(client):
    auth = pair(client)
    pid = client.post("/api/projects", json={"name": "House"}).json()["id"]
    client.put(f"/api/projects/{pid}/model", json=fixture("compliant_house"), headers=auth)
    job_id, first = run_check(client, pid)
    _, again = None, []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        again = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    assert again == first


def test_location_resolves_rule_sets_for_revit_exports(client):
    auth = pair(client)
    model = fixture("compliant_house")
    model["project"]["rulesets"] = {"value": None, "source": "default"}
    model["project"]["authority_id"] = {"value": None, "source": "default"}
    pid = client.post("/api/projects", json={"name": "Revit export"}).json()["id"]
    client.put(f"/api/projects/{pid}/model", json=model, headers=auth)
    _, events = run_check(client, pid)
    assert events[-1]["stage"] == "done"
    assert any("Pune Municipal Corporation" in (e.get("msg") or "") for e in events)
    assert client.resolver_calls == [(18.4655, 73.896)]


def test_unsupported_location_ends_with_a_clear_error(client):
    auth = pair(client)
    model = fixture("compliant_house")
    model["project"]["rulesets"] = {"value": None, "source": "default"}
    model["project"]["location"] = {"value": {"lat": 41.88, "lon": -87.63}, "source": "model"}
    pid = client.post("/api/projects", json={"name": "Template location"}).json()["id"]
    client.put(f"/api/projects/{pid}/model", json=model, headers=auth)
    job_id, events = run_check(client, pid)
    assert events[-1]["stage"] == "error"
    assert "Chicago is not covered yet" in events[-1]["error"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["status"], job["stage"]) == ("error", "resolve_authority")


def test_brief_answers_unlock_checks(client):
    auth = pair(client)
    pid = client.post("/api/projects", json={"name": "Site"}).json()["id"]
    model = fixture("compliant_house")
    model["site"]["edges"][0]["road_width_m"] = {"value": None, "source": "default"}
    client.put(f"/api/projects/{pid}/model", json=model, headers=auth)
    _, ev = run_check(client, pid)
    before = client.get(f"/api/reports/{ev[-1]['report_id']}").json()
    assert any(q["path"] == "site.edges" for q in before["questions"])

    r = client.patch(f"/api/projects/{pid}/brief", json={"site.edges[e1].road_width_m": 9.0})
    assert r.json()["brief"]["site.edges[e1].road_width_m"] == {"value": 9.0, "source": "declared"}
    _, ev = run_check(client, pid)
    after = client.get(f"/api/reports/{ev[-1]['report_id']}").json()
    assert after["summary"]["unverifiable"] < before["summary"]["unverifiable"]
    assert after["fsi"]["max_permissible"] == 2.0


@pytest.mark.parametrize(
    ("headers", "detail"),
    [({}, "Pair this Revit"), ({"Authorization": "Bearer nope"}, "no longer valid")],
)
def test_model_upload_needs_a_valid_token(client, headers, detail):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/model", json=fixture("compliant_house"), headers=headers)
    assert r.status_code == 401 and detail in r.json()["detail"]


def test_bad_inputs_get_clear_errors(client):
    auth = pair(client)
    assert client.post("/api/pair/complete", json={"code": "000000"}).status_code == 400
    assert client.post("/api/pair/complete", json={"code": "12ab"}).status_code == 422
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    bad = fixture("compliant_house")
    del bad["site"]
    r = client.put(f"/api/projects/{pid}/model", json=bad, headers=auth)
    assert r.status_code == 422 and "BuildingModel contract" in r.json()["detail"]
    assert client.post(f"/api/projects/{pid}/checks").status_code == 409  # no model yet
    assert (
        client.put(
            "/api/projects/nope/model", json=fixture("compliant_house"), headers=auth
        ).status_code
        == 404
    )
    assert client.get("/api/reports/nope").status_code == 404


def test_rules_usage_and_health(client):
    rules = client.get("/api/rules").json()
    assert len(rules) >= 22
    tod = client.get("/api/rules/pmc.tod.max-fsi").json()
    assert tod["clause"]["ref"] == "14.2.1.2" and "pmc.tod_max_fsi" in tod["tables"]
    assert "site.edges[*].road_width_m" in tod["requires"]
    assert client.get("/api/usage").json() == {"models": [], "search": []}
    assert client.get("/api/health").json()["ok"] is True


def test_unsupported_location_suggests_official_documents(tmp_path):
    def resolver(lat, lon, store=None):
        return Resolution(None, None, "Nagpur is not covered yet", {"city": "Nagpur"})

    def discover(place):
        assert place == "Nagpur"
        return [{"title": "Nagpur DCR 2018", "url": "https://nmcnagpur.gov.in/dcr.pdf"}]

    app = create_app(
        tmp_path / "d.sqlite",
        runner_factory=lambda s, rb: JobRunner(s, rb, resolver=resolver, discover=discover),
    )
    with TestClient(app) as c:
        auth = pair(c)
        model = fixture("compliant_house")
        model["project"]["rulesets"] = {"value": None, "source": "default"}
        pid = c.post("/api/projects", json={"name": "Nagpur"}).json()["id"]
        c.put(f"/api/projects/{pid}/model", json=model, headers=auth)
        _, events = run_check(c, pid)
    assert events[-1]["stage"] == "error"
    assert "Nagpur DCR 2018 (https://nmcnagpur.gov.in/dcr.pdf)" in events[-1]["error"]


@pytest.mark.parametrize(
    "name",
    ["compliant_house", "violating_apartment", "missing_site", "demo_apartment", "demo_house"],
)
def test_each_fixture_create_model_check_report_bcf(client, name):
    """P4.6: create → model → check → SSE done → report (same as the golden file) → BCF."""
    import io
    import zipfile

    auth = pair(client)
    pid = client.post("/api/projects", json={"name": name}).json()["id"]
    assert client.put(f"/api/projects/{pid}/model", json=fixture(name), headers=auth).is_success
    _, events = run_check(client, pid)
    assert events[-1]["stage"] == "done", events[-1]
    report = client.get(f"/api/reports/{events[-1]['report_id']}").json()
    golden = json.loads(
        (REPO_ROOT / "fixtures" / "expected" / f"{name}.report.json").read_text("utf-8")
    )

    # The golden files are pure engine output; through the API the overlays stage also resolves the
    # metro TOD status from the location, which may only settle TOD rules as not applicable.
    def by_key(rep):
        return {(r["rule_id"], (r["element"] or {}).get("id")): r["status"] for r in rep["results"]}

    # A TOD rule that becomes not applicable for every unit collapses to one rule-level line.
    def outside_tod(rep):
        return {k: v for k, v in by_key(rep).items() if not k[0].startswith("pmc.tod.")}

    assert outside_tod(report) == outside_tod(golden)
    for (rule_id, _), status in by_key(report).items():
        if rule_id.startswith("pmc.tod.") and status != "not_applicable":
            assert by_key(golden).get((rule_id, _)) == status, rule_id
    assert report["summary"]["fail"] == golden["summary"]["fail"]
    bcf = client.get(f"/api/reports/{report['id']}/bcf")
    assert bcf.status_code == 200
    topics = [n for n in zipfile.ZipFile(io.BytesIO(bcf.content)).namelist() if "markup" in n]
    assert len(topics) == report["summary"]["fail"]


def test_suggestions_for_a_drawing(client, monkeypatch):
    from compliance.agents import planning

    site = {"locality": "Kasba Peth", "landuse": "residential", "landuse_name": None}
    monkeypatch.setattr(planning, "lookup", lambda *a, **k: site)
    pid = client.post("/api/projects", json={"name": "house"}).json()["id"]
    data = (REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf").read_bytes()
    assert client.post(f"/api/projects/{pid}/dxf", content=data).status_code == 200
    r = client.get(f"/api/projects/{pid}/suggestions", params={"lat": 18.5195, "lon": 73.8553})
    got = {s["path"]: s for s in r.json()}
    assert got["project.congested_area"]["suggested"]["value"] is True
    assert got["project.occupancy"]["suggested"]["value"]["subdivision"] == "A-2"
    assert got["project.zone"]["current"]["source"] == "default"
