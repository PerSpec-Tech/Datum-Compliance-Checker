"""P10.2: 2D DXF in the PreDCR layer standard reads to the same results as the 3D fixture, except
what a plan can't show (room clear heights, door heights)."""

import json
from collections import Counter

import pytest

from compliance.adapters.dxf import floor_numbers, layer_report, read
from compliance.config import REPO_ROOT
from compliance.engine.brief import apply_brief
from compliance.engine.evaluate import evaluate
from compliance.engine.rules import load_rulebase
from compliance.schemas import errors

NAMES = ["demo_house", "demo_apartment"]
PLAN_BLIND = {"udcpr2020.ch9.exit-door-height", "udcpr2020.ch9.habitable-height-min",
              "udcpr2020.ch9.shop-height-min", "udcpr2020.ch9.kitchen-height-min",
              "udcpr2020.ch9.habitable-height-max", "udcpr2020.ch9.bath-wc-height-min",
              "pmc.tod.tenement-max-carpet", "pmc.tod.tenement-min-carpet"}  # fmt: skip


def fixture(name):
    return json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))


def declared(fx):
    """What the web wizard and brief supply for a 2D drawing: location and planning facts."""
    p = fx["project"]
    out = {f"project.{k}": p[k] for k in ("location", "rulesets", "authority_id", "occupancy",
                                         "building_type", "congested_area", "zone")}  # fmt: skip
    out.update(
        {f"project.overlays.{k}": p["overlays"][k] for k in ("metro_tod", "plot_share_in_tod")}
    )
    return out


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


@pytest.mark.parametrize(
    ("name", "nums"),
    [
        ("Ground Floor Plan", [0]),
        ("First Floor Plan", [1]),
        ("TYPICAL-2-4 FLOOR PLAN", [2, 3, 4]),
        ("TYPICAL-1,4 FLOOR PLAN", [1, 4]),
        ("TYPICAL-2&3 FLOOR PLAN", [2, 3]),
        ("TYPICAL-1-5 FLOOR PLAN", [1, 2, 3, 4, 5]),
        ("Site plan", []),
    ],
)
def test_floor_names_follow_predcr(name, nums):
    assert floor_numbers(name) == nums


@pytest.mark.parametrize("name", NAMES)
def test_sample_reads_to_a_valid_model(name):
    model, warnings = read(REPO_ROOT / "fixtures" / "dxf" / f"{name}.dxf")
    assert errors("building-model.schema.json", model) == []
    assert model["meta"]["source_kind"] == "dxf"
    fx = fixture(name)
    assert len(model["spaces"]) == len(fx["spaces"])
    assert len(model["doors"]) == len(fx["doors"])
    assert [lv["elevation_m"] for lv in model["levels"]] == [
        lv["elevation_m"] for lv in sorted(fx["levels"], key=lambda lv: lv["elevation_m"])
    ]
    assert model["building"]["roof_top_m"] == fx["building"]["roof_top_m"]
    road = next(e for e in model["site"]["edges"] if e["kind"]["value"] == "road")
    assert road["road_width_m"]["value"] == next(
        e["road_width_m"]["value"] for e in fx["site"]["edges"] if e["kind"]["value"] == "road"
    )
    st, fst = model["stairs"][0], fx["stairs"][0]
    assert (st["min_run_width_m"], st["riser_m"], st["tread_m"]) == (
        fst["min_run_width_m"], fst["riser_m"], fst["tread_m"],
    )  # fmt: skip
    assert any("slab" in w for w in warnings)  # the clear-height assumption is stated


@pytest.mark.parametrize("name", NAMES)
def test_same_results_as_3d_except_what_a_plan_cannot_show(name, rulebase):
    model, _ = read(REPO_ROOT / "fixtures" / "dxf" / f"{name}.dxf")
    fx = fixture(name)
    model, skipped = apply_brief(model, declared(fx))
    assert skipped == []
    rules = rulebase.select(["nbc2016", "udcpr2020", "pmc"])

    def outcome(m):
        return Counter(
            (r["rule_id"], r["status"], r["fix_by"] and r["fix_by"]["amount"])
            for r in evaluate(m, rules, rulebase.tables)
            if r["rule_id"] not in PLAN_BLIND
        )

    assert outcome(model) == outcome(fx)


def test_apartment_finds_the_planted_issues_a_plan_can_show(rulebase):
    model, _ = read(REPO_ROOT / "fixtures" / "dxf" / "demo_apartment.dxf")
    model, _ = apply_brief(model, declared(fixture("demo_apartment")))
    fails = sorted(
        r["rule_id"]
        for r in evaluate(model, rulebase.select(["nbc2016", "udcpr2020", "pmc"]), rulebase.tables)
        if r["status"] == "fail"
    )
    assert fails == [
        "pmc.ch10.height-road-width",
        "pmc.tod.max-fsi", "pmc.tod.mixed-use-road-width", "pmc.tod.tenement-min-carpet",
        "udcpr2020.ch6.front-margin", "udcpr2020.ch6.side-rear-margin",
        "udcpr2020.ch9.exit-door-width", "udcpr2020.ch9.stair-width-residential",
    ]  # fmt: skip


def test_layer_report_names_predcr_roles_and_unknown_layers(tmp_path):
    import ezdxf

    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True, dxfattribs={"layer": "_main plot"})
    msp.add_lwpolyline([(1, 1), (2, 1), (2, 2)], close=True, dxfattribs={"layer": "MISC-STUFF"})
    msp.add_lwpolyline([(3, 1), (4, 1), (4, 2)], close=True, dxfattribs={"layer": "A-WALL"})
    path = tmp_path / "x.dxf"
    doc.saveas(path)
    report = {r["layer"]: r["role"] for r in layer_report(path)}
    assert (
        report["_main plot"] == "plot"
        and report["MISC-STUFF"] is None
        and report["A-WALL"] == "ignore"
    )
    assert {r["layer"]: r["role"] for r in layer_report(path, {"A-WALL": "room"})}[
        "A-WALL"
    ] == "room"


def test_upload_and_remap_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from compliance.main import create_app

    app = create_app(tmp_path / "d.sqlite")
    data = (REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "2D"}).json()["id"]
        r = c.post(f"/api/projects/{pid}/dxf", content=data)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["counts"]["spaces"] == 14 and body["unmapped"] == 0
        assert c.get(f"/api/projects/{pid}/model").json()["model"]["meta"]["source_kind"] == "dxf"
        # Remap: treat the rooms layer as ignored → no rooms
        r = c.put(f"/api/projects/{pid}/dxf/roles", json={"_Room": "ignore"})
        assert r.json()["counts"]["spaces"] == 0
        assert (
            c.put(f"/api/projects/{pid}/dxf/roles", json={"_Room": None}).json()["counts"]["spaces"]
            == 14
        )
        assert c.put(f"/api/projects/{pid}/dxf/roles", json={"_Room": "kitchen"}).status_code == 422
        assert c.post(f"/api/projects/{pid}/dxf", content=b"AC1032 binary").status_code == 415


class _FakeLLM:
    """Stands in for Nemotron: answers from a fixed mapping."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def chat(self, role, messages, **kw):
        from types import SimpleNamespace

        sent = [json.loads(line)["layer"] for line in messages[1]["content"].splitlines()]
        self.calls.append((role, kw.get("purpose"), sent))
        rows = [
            {"layer": n, "role": self.answers.get(n, (None, 0.2))[0],
             "confidence": self.answers.get(n, (None, 0.2))[1]}
            for n in sent
        ]  # fmt: skip
        return SimpleNamespace(data={"layers": rows})


def test_layer_agent_suggests_roles_for_office_layer_names(rulebase):
    import sys

    from compliance.adapters.dxf import layer_profiles
    from compliance.agents.layers import suggest_roles

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from make_sample_dxf import OFFICE_NAMES

    path = REPO_ROOT / "fixtures" / "dxf" / "demo_house_office.dxf"
    truth = {v: k for k, v in OFFICE_NAMES.items()}
    from compliance.adapters.dxf import predcr_roles, _key  # noqa: I001

    roles = {office: predcr_roles()[_key(predcr)] for office, predcr in truth.items()}
    answers = {k: (v, 0.9) for k, v in roles.items()}
    # The model swaps floor frames and section heights; geometry must settle it.
    answers["SHEET FRAMES"] = ("floor_height", 0.9)
    answers["SECTION-FLOOR HT"] = ("floor", 0.9)
    answers["A-WALL"] = ("room", 0.4)  # low confidence: dropped, stays unknown
    llm = _FakeLLM(answers)
    sug = suggest_roles(layer_profiles(path), llm)
    assert llm.calls[0][:2] == ("fast", "layer_roles")
    assert (
        sug["SHEET FRAMES"]["role"] == "floor" and sug["SECTION-FLOOR HT"]["role"] == "floor_height"
    )
    assert "A-WALL" not in sug

    office, _ = read(path, {k: v["role"] for k, v in sug.items()})
    predcr, _ = read(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf")
    rules = rulebase.select(["nbc2016", "udcpr2020", "pmc"])
    facts = declared(fixture("demo_house"))

    def outcome(m):
        m, _ = apply_brief(m, facts)
        return Counter((r["rule_id"], r["status"]) for r in evaluate(m, rules, rulebase.tables))

    assert outcome(office) == outcome(predcr)


def test_upload_uses_suggestions_and_user_choice_wins(tmp_path):
    from fastapi.testclient import TestClient

    from compliance.main import create_app

    app = create_app(tmp_path / "s.sqlite")
    app.state.llm = _FakeLLM(
        {"A-AREA-ROOMS": ("room", 0.95), "A-WALL": ("ignore", 0.9), "SHEET FRAMES": ("floor", 0.9),
         "SECTION-FLOOR HT": ("floor_height", 0.9), "BUILDING OUTLINE": ("footprint", 0.9),
         "SITE BOUNDARY": ("plot", 0.9)}
    )  # fmt: skip
    data = (REPO_ROOT / "fixtures" / "dxf" / "demo_house_office.dxf").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "office"}).json()["id"]
        body = c.post(f"/api/projects/{pid}/dxf", content=data).json()
        rows = {r["layer"]: r for r in body["layers"]}
        assert (
            rows["A-AREA-ROOMS"]["role"] == "room" and rows["A-AREA-ROOMS"]["source"] == "suggested"
        )
        assert rows["A-AREA-ROOMS"]["confidence"] == 0.95
        assert body["counts"]["spaces"] == 14
        body = c.put(f"/api/projects/{pid}/dxf/roles", json={"A-AREA-ROOMS": "ignore"}).json()
        rows = {r["layer"]: r for r in body["layers"]}
        assert rows["A-AREA-ROOMS"]["source"] == "user" and body["counts"]["spaces"] == 0


@pytest.mark.parametrize("name", NAMES)
def test_floor_plans_found_without_floor_frames(name, rulebase):
    """No _Floor frames: plans are found from room outlines and named from their titles."""
    model, warnings = read(REPO_ROOT / "fixtures" / "dxf" / f"{name}.dxf", {"_Floor": "ignore"})
    framed, _ = read(REPO_ROOT / "fixtures" / "dxf" / f"{name}.dxf")
    assert any("No _Floor frames" in w for w in warnings)
    facts = declared(fixture(name))
    rules = rulebase.select(["nbc2016", "udcpr2020", "pmc"])

    def outcome(m):
        m, _ = apply_brief(m, facts)
        return Counter((r["rule_id"], r["status"]) for r in evaluate(m, rules, rulebase.tables))

    assert outcome(model) == outcome(framed)


def test_untitled_plans_are_numbered_left_to_right(tmp_path):
    import ezdxf

    doc = ezdxf.readfile(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf")
    msp = doc.modelspace()
    for e in [e for e in msp if e.dxf.layer == "_Floor"]:
        msp.delete_entity(e)  # frames and their titles gone
    path = tmp_path / "untitled.dxf"
    doc.saveas(path)
    model, warnings = read(path)
    assert [lv["name"] for lv in model["levels"]] == ["Ground Floor", "First Floor"]
    assert any("numbered left to right" in w for w in warnings)


def test_drawing_endpoint_serves_floor_vectors(tmp_path):
    from fastapi.testclient import TestClient

    from compliance.main import create_app

    app = create_app(tmp_path / "dr.sqlite")
    data = (REPO_ROOT / "fixtures" / "dxf" / "demo_apartment.dxf").read_bytes()
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "2D"}).json()["id"]
        assert c.get(f"/api/projects/{pid}/drawing").status_code == 404
        c.post(f"/api/projects/{pid}/dxf", content=data)
        floors = c.get(f"/api/projects/{pid}/drawing").json()["floors"]
        model = c.get(f"/api/projects/{pid}/model").json()["model"]
    assert [f["nums"] for f in floors] == [[0], [1], list(range(2, 12))]
    typical = floors[2]
    assert typical["paths"]["wall"] and typical["fills"] and typical["paths"]["furniture"]
    # The drawing sits where the model's rooms are (same per-floor alignment).
    xs = [v for p in typical["paths"]["wall"] for v in p[0::2]]
    fx = [p[0] for p in model["building"]["footprint"]]
    assert min(xs) == pytest.approx(min(fx), abs=0.3) and max(xs) == pytest.approx(max(fx), abs=0.3)


def test_floors_line_up_on_the_stair_core_when_a_floor_projects(tmp_path):
    """A first floor that projects 1.5 m to the west: matching the outline's corner would shift it
    1.5 m the wrong way; matching the stair core keeps its rooms over the ground floor's."""
    import ezdxf

    from compliance.adapters import dxf as dxf_mod

    src = REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf"
    d = dxf_mod._load(src, {})
    assert d.scale == 1
    for sh in d.polys["floor"]:
        sh.name = dxf_mod._name_inside(sh, d.texts, "floor")
    first = next(fr for fr, nums in dxf_mod._floor_frames(d, []) if nums == [1])
    on_first = first.poly.contains
    fsi = [s.poly for s in d.polys["fsi_resi"] if on_first(s.poly.representative_point())]
    x0, y0, _, _ = fsi[0].bounds
    doc = ezdxf.readfile(src)
    balcony = [(x0 - 1.5, y0 + 1), (x0, y0 + 1), (x0, y0 + 4), (x0 - 1.5, y0 + 4)]
    for layer in ("_ResiFSI", "_Room"):
        doc.modelspace().add_lwpolyline(balcony, close=True, dxfattribs={"layer": layer})
    label = doc.modelspace().add_text("Balcony", dxfattribs={"layer": "_Room", "height": 0.2})
    label.set_placement((x0 - 0.75, y0 + 2.5))
    path = tmp_path / "projecting.dxf"
    doc.saveas(path)

    model, warnings = read(path)
    stair = {s["level_id"]: s["polygon"] for s in model["spaces"] if s["usage"]["value"] == "stair"}
    assert stair["L1"] == stair["L0"]  # the core is over the core
    assert any("stair / lift core" in w and "First Floor" in w for w in warnings)
    balcony_room = next(s for s in model["spaces"] if s["name"] == "Balcony")
    fp_x0 = min(p[0] for p in model["building"]["footprint"])
    assert min(p[0] for p in balcony_room["polygon"]) == pytest.approx(fp_x0 - 1.5, abs=0.01)
