"""P6.1: IFC adapter — the generated samples read back to the same model and the same results."""

import json

import pytest
from fastapi.testclient import TestClient

from compliance.adapters.ifc import read
from compliance.agents.authority import Resolution
from compliance.config import REPO_ROOT
from compliance.engine.brief import apply_brief
from compliance.engine.derived import compute
from compliance.engine.evaluate import evaluate
from compliance.engine.rules import load_rulebase
from compliance.jobs import JobRunner
from compliance.main import create_app
from compliance.schemas import errors

NAMES = ["compliant_house", "violating_apartment", "demo_apartment", "demo_house"]


def fixture(name):
    return json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))


def server_facts(model):
    """What the server works out itself during a job (authority + metro overlay from location)."""
    p = model["project"]
    out = {f"project.overlays.{k}": p["overlays"][k] for k in ("metro_tod", "plot_share_in_tod")}
    out["project.rulesets"] = p["rulesets"]
    out["project.authority_id"] = p["authority_id"]
    return out


def declared_facts(model):
    """Everything a person could declare in the brief (used to prove declared answers win)."""
    out = server_facts(model)
    p = model["project"]
    for key in ("occupancy", "zone", "congested_area", "building_type"):
        out[f"project.{key}"] = p[key]
    out["site.plot_area_declared_m2"] = model["site"]["plot_area_declared_m2"]
    for e in model["site"]["edges"]:
        for k in ("kind", "road_width_m", "road_width_basis"):
            out[f"site.edges[{e['id']}].{k}"] = e[k]
    return out


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


@pytest.mark.parametrize("name", NAMES)
def test_sample_reads_to_a_valid_model(name):
    model, warnings = read(REPO_ROOT / "fixtures" / "ifc" / f"{name}.ifc")
    assert errors("building-model.schema.json", model) == []
    assert warnings == []
    assert model["meta"]["source_kind"] == "ifc"
    assert all(len(s["source_id"]) == 22 for s in model["spaces"])  # IFC GlobalIds


@pytest.mark.parametrize("name", NAMES)
def test_geometry_matches_the_fixture(name):
    model, _ = read(REPO_ROOT / "fixtures" / "ifc" / f"{name}.ifc")
    got, want = compute(model).values, compute(fixture(name)).values
    for key in ("footprint_area_m2", "built_up_m2", "building_height_m", "floors_above_ground"):
        assert got[key] == pytest.approx(want[key], abs=1e-3), key
    assert got["setback_m"] == pytest.approx(want["setback_m"], abs=1e-3)
    assert got["space_min_width_m"] == pytest.approx(want["space_min_width_m"], abs=1e-3)


@pytest.mark.parametrize("name", NAMES)
def test_site_and_planning_facts_come_from_the_model(name):
    model, _ = read(REPO_ROOT / "fixtures" / "ifc" / f"{name}.ifc")
    fx = fixture(name)
    for key in ("occupancy", "zone", "congested_area", "building_type"):
        assert model["project"][key]["value"] == fx["project"][key]["value"], key
        assert model["project"][key]["source"] == "model", key
    assert model["site"]["plot_area_declared_m2"]["value"] == pytest.approx(
        fx["site"]["plot_area_declared_m2"]["value"]
    )
    for got, want in zip(model["site"]["edges"], fx["site"]["edges"], strict=True):
        assert got["kind"]["value"] == want["kind"]["value"], got["id"]
        assert got["road_width_m"]["value"] == want["road_width_m"]["value"], got["id"]
    roads = [e for e in model["site"]["edges"] if e["kind"]["value"] == "road"]
    assert roads and all(e["road_width_m"]["note"] == "measured across the road" for e in roads)


@pytest.mark.parametrize("name", NAMES)
def test_same_results_as_the_fixture_with_nothing_declared(name, rulebase):
    model, _ = read(REPO_ROOT / "fixtures" / "ifc" / f"{name}.ifc")
    model, skipped = apply_brief(model, server_facts(fixture(name)))
    assert skipped == []
    rules = rulebase.select(["nbc2016", "udcpr2020", "pmc"])

    def outcome(m):
        return sorted(
            (r["rule_id"], r["status"], r["fix_by"] and r["fix_by"]["amount"])
            for r in evaluate(m, rules, rulebase.tables)
        )

    assert outcome(model) == outcome(fixture(name))


@pytest.mark.parametrize("name", NAMES)
def test_same_results_as_the_fixture_once_facts_are_declared(name, rulebase):
    model, _ = read(REPO_ROOT / "fixtures" / "ifc" / f"{name}.ifc")
    fx = fixture(name)
    model, skipped = apply_brief(model, declared_facts(fx))
    assert skipped == []
    rules = rulebase.select(["nbc2016", "udcpr2020", "pmc"])

    def outcome(m):
        return sorted(
            (r["rule_id"], r["status"], r["fix_by"] and r["fix_by"]["amount"])
            for r in evaluate(m, rules, rulebase.tables)
        )

    assert outcome(model) == outcome(fx)


def test_upload_endpoint_round_trip(tmp_path):
    pmc = Resolution("pmc", ["nbc2016", "udcpr2020", "pmc"], "PMC (test)")
    app = create_app(
        tmp_path / "i.sqlite",
        runner_factory=lambda s, rb: JobRunner(s, rb, resolver=lambda *a: pmc),
    )
    data = (REPO_ROOT / "fixtures" / "ifc" / "violating_apartment.ifc").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "IFC"}).json()["id"]
        r = c.post(
            f"/api/projects/{pid}/ifc",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["counts"]["doors"] == 2 and body["has_site_boundary"] is True
        assert c.get(f"/api/models/{body['model_version']}/ifc").content == data
        assert c.post(f"/api/projects/{pid}/ifc", content=b"not ifc").status_code == 415
        assert c.post(f"/api/projects/{pid}/ifc", content=b"").status_code == 400


def test_bcf_has_one_topic_per_failure_with_ifc_guids(tmp_path):
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    pmc = Resolution("pmc", ["nbc2016", "udcpr2020", "pmc"], "PMC (test)")
    app = create_app(
        tmp_path / "b.sqlite",
        runner_factory=lambda s, rb: JobRunner(s, rb, resolver=lambda *a: pmc),
    )
    data = (REPO_ROOT / "fixtures" / "ifc" / "violating_apartment.ifc").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "IFC"}).json()["id"]
        c.post(f"/api/projects/{pid}/ifc", content=data)
        answers = {k: v["value"] for k, v in declared_facts(fixture("violating_apartment")).items()}
        c.patch(f"/api/projects/{pid}/brief", json=answers)
        job = c.post(f"/api/projects/{pid}/checks").json()["job_id"]
        with c.stream("GET", f"/api/jobs/{job}/events") as r:
            last = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")][-1]
        report = c.get(f"/api/reports/{last['report_id']}").json()
        bcf = c.get(f"/api/reports/{last['report_id']}/bcf")
    assert report["summary"]["fail"] == 13
    z = zipfile.ZipFile(io.BytesIO(bcf.content))
    markups = [n for n in z.namelist() if n.endswith("markup.bcf")]
    assert len(markups) == 13 and "bcf.version" in z.namelist()
    guids = {
        c.get("IfcGuid")
        for n in z.namelist()
        if n.endswith(".bcfv")
        for c in ET.fromstring(z.read(n)).iter("Component")
    }
    assert len(guids) >= 5 and all(len(g) == 22 for g in guids)


def test_mesh_and_merged_model_endpoints(tmp_path):
    app = create_app(tmp_path / "m.sqlite")
    data = (REPO_ROOT / "fixtures" / "ifc" / "violating_apartment.ifc").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "IFC"}).json()["id"]
        assert c.get(f"/api/projects/{pid}/model").status_code == 404
        version = c.post(f"/api/projects/{pid}/ifc", content=data).json()["model_version"]
        c.patch(f"/api/projects/{pid}/brief", json={"project.zone": "residential"})
        body = c.get(f"/api/projects/{pid}/model").json()
        assert body["model_version"] == version
        assert body["model"]["project"]["zone"] == {"value": "residential", "source": "declared"}
        mesh = c.get(f"/api/models/{version}/mesh").json()
        model = read(REPO_ROOT / "fixtures" / "ifc" / "violating_apartment.ifc")[0]
        assert {s["guid"] for s in mesh["spaces"]} == {s["source_id"] for s in model["spaces"]}
        stair = model["stairs"][0]["source_id"]
        assert any(e["parent"] == stair for e in mesh["elements"])  # flight → IfcStair result
        assert all(len(e["f"]) % 3 == 0 and e["v"] for e in mesh["elements"])
        assert c.get("/api/models/nope/mesh").status_code == 404
