"""P9.1: the live pack reproduces the engine's verdicts for everything it covers."""

import json

import pytest
from shapely.geometry import LineString, Polygon

from compliance.config import REPO_ROOT
from compliance.engine.live import STEP_M, build_live_pack
from compliance.engine.report import build_report
from compliance.engine.rules import load_rulebase
from compliance.schemas import errors

NAMES = ["demo_apartment", "demo_house", "compliant_house", "violating_apartment"]
OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


def pack_for(name, rulebase):
    m = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
    report = build_report(m, rulebase, project_id="p", model_version="v")
    return m, report, build_live_pack(m, rulebase, report)


@pytest.mark.parametrize("name", NAMES)
def test_pack_is_valid(name, rulebase):
    _, _, pack = pack_for(name, rulebase)
    assert errors("live-pack.schema.json", pack) == []


@pytest.mark.parametrize("name", NAMES)
def test_margin_verdicts_match_the_engine(name, rulebase):
    """Footprint distance to each side against the pack's margin gives the engine's verdict."""
    m, report, pack = pack_for(name, rulebase)
    fp = Polygon(m["building"]["footprint"])
    for e in pack["edges"]:
        engine = [
            r["status"]
            for r in report["results"]
            if (r["element"] or {}).get("id") == e["edge_id"] and r["status"] in ("pass", "fail")
        ]
        if not engine or e["margin_m"] is None:
            continue
        gap = fp.distance(LineString([e["a"], e["b"]]))
        live = "pass" if gap >= e["margin_m"] - 1e-9 else "fail"
        assert live == ("fail" if "fail" in engine else "pass"), (name, e["edge_id"], gap)


@pytest.mark.parametrize("name", NAMES)
def test_footprint_inside_envelope_iff_no_margin_fails(name, rulebase):
    m, report, pack = pack_for(name, rulebase)
    if pack["envelope"] is None:
        pytest.skip("margins unknown")
    fails = [
        r
        for r in report["results"]
        if (r["element"] or {}).get("kind") == "site.edges" and r["status"] == "fail"
    ]
    footprint = Polygon(m["building"]["footprint"])
    inside = Polygon(pack["envelope"]).buffer(1e-6).contains(footprint)
    assert inside == (not fails)


@pytest.mark.parametrize("name", NAMES)
def test_threshold_verdicts_match_the_engine(name, rulebase):
    m, report, pack = pack_for(name, rulebase)
    elements = {k: {e["id"]: e for e in m[k]} for k in ("spaces", "doors", "stairs", "units")}
    status = {
        (r["rule_id"], (r["element"] or {}).get("id")): r["status"] for r in report["results"]
    }
    checked = 0
    for t in pack["thresholds"]:
        for eid in t["element_ids"]:
            v = elements[t["for_each"]][eid].get(t["field"])
            want = status[(t["rule_id"], eid)]
            if v is None:
                assert want == "unverifiable"
                continue
            assert ("pass" if OPS[t["op"]](v, t["limit"]) else "fail") == want, (t["rule_id"], eid)
            checked += 1
    assert checked > 0


def test_margin_table_follows_height(rulebase):
    """Side margins above 3 floors are H/5 (UDCPR): the table must say so at every height."""
    _, _, pack = pack_for("demo_apartment", rulebase)
    side = next(e for e in pack["edges"] if e["edge_id"] == "e2")
    assert side["margin_by_height"][round(20 / STEP_M)] == pytest.approx(4.0)
    assert side["margin_by_height"][round(36.4 / STEP_M)] == pytest.approx(side["margin_m"])
    road = next(e for e in pack["edges"] if e["edge_id"] == "e1")
    assert road["margin_by_height"] == []  # constant


def test_height_limit_from_the_road_width(rulebase):
    """The tower stands on a 10.5 m road: over 36 m needs a 12 m road (UDCPR 10.1.1)."""
    _, _, pack = pack_for("demo_apartment", rulebase)
    h = pack["height"]
    assert h["limit_m"] == pytest.approx(36.0)
    assert h["limit_clause_ref"] == "10.1.1"
    _, _, house = pack_for("demo_house", rulebase)
    assert house["height"]["limit_m"] is None or house["height"]["limit_m"] >= 36.0


def test_pack_is_saved_after_a_check_and_served(tmp_path):
    from fastapi.testclient import TestClient

    from compliance.agents.authority import Resolution
    from compliance.jobs import JobRunner
    from compliance.main import create_app

    pmc = Resolution("pmc", ["nbc2016", "udcpr2020", "pmc"], "PMC (test)")
    app = create_app(
        tmp_path / "l.sqlite",
        runner_factory=lambda s, rb: JobRunner(s, rb, resolver=lambda *a: pmc),
    )
    data = (REPO_ROOT / "fixtures" / "ifc" / "demo_house.ifc").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "live"}).json()["id"]
        assert c.get(f"/api/projects/{pid}/live-pack").status_code == 404
        c.post(f"/api/projects/{pid}/ifc", content=data)
        job = c.post(f"/api/projects/{pid}/checks").json()["job_id"]
        with c.stream("GET", f"/api/jobs/{job}/events") as r:
            last = [json.loads(x[5:]) for x in r.iter_lines() if x.startswith("data:")][-1]
        pack = c.get(f"/api/projects/{pid}/live-pack").json()
    assert pack["report_id"] == last["report_id"]
    assert pack["envelope"] and pack["fsi"]["max_built_up_m2"] == 600.0


def test_golden_live_pack_for_the_addin_tests(rulebase, request):
    """fixtures/expected/demo_apartment.live-pack.json is what the C# live engine is tested on."""
    path = REPO_ROOT / "fixtures" / "expected" / "demo_apartment.live-pack.json"
    _, _, pack = pack_for("demo_apartment", rulebase)
    pack = {**pack, "created_at": "2000-01-01T00:00:00+00:00", "ruleset_version": "volatile",
            "report_id": "volatile"}  # fmt: skip
    if request.config.getoption("--update-golden") or not path.exists():
        path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
        pytest.skip(f"wrote {path.name}")
    assert json.loads(path.read_text("utf-8")) == pack
