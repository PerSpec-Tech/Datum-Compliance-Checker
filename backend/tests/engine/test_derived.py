"""P2.2: derived values, hand-checked against the three fixtures."""

import json

import pytest

from compliance.config import REPO_ROOT
from compliance.engine.derived import compute, inputs_for


def model(name):
    return json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))


def test_compliant_house():
    d = compute(model("compliant_house")).values
    assert d["plot_area_m2"] == {"value": 300.0, "source": "declared"}
    assert d["footprint_area_m2"] == pytest.approx(94.5)  # 9 × 10.5
    assert d["ground_coverage"] == pytest.approx(0.315)
    assert d["built_up_m2"] == pytest.approx(189.0)  # 2 × 94.5
    assert d["far"] == pytest.approx(0.63)
    assert d["building_height_m"] == pytest.approx(6.4)
    assert d["floors_above_ground"] == 2
    assert d["setback_m"] == pytest.approx({"e1": 4.5, "e2": 3.0, "e3": 5.0, "e4": 3.0})
    assert d["road_edges"] == ["e1"]
    assert d["front_road_width_m"] == 9.0
    assert d["space_min_width_m"]["S1"] == pytest.approx(3.5)  # 9 × 3.5 living
    assert d["residential_carpet_m2"] == 160.0
    assert d["small_unit_carpet_share"] == 0.0


def test_violating_apartment():
    d = compute(model("violating_apartment")).values
    assert d["plot_area_m2"]["value"] == 1000.0
    assert d["footprint_area_m2"] == pytest.approx(589.0)  # 19 × 31
    assert d["built_up_m2"] == pytest.approx(3200.0)  # 5 × 640
    assert d["far"] == pytest.approx(3.2)
    assert d["building_height_m"] == pytest.approx(14.75)
    assert d["floors_above_ground"] == 5
    assert d["setback_m"] == pytest.approx({"e1": 6.0, "e2": 3.0, "e3": 3.0, "e4": 3.0})
    assert d["front_road_width_m"] == 10.5
    assert d["residential_carpet_m2"] == pytest.approx(342.0)  # 22 + 4 × 80
    assert d["small_unit_carpet_share"] == pytest.approx(22 / 342, rel=1e-5)


def test_missing_site_gives_none_not_guesses():
    d = compute(model("missing_site")).values
    assert d["plot_area_m2"]["value"] is None
    assert d["ground_coverage"] is None
    assert d["far"] is None
    assert d["built_up_m2"] == pytest.approx(189.0)  # areas are still known
    assert d["building_height_m"] is None  # no ground level
    assert d["setback_m"] == {}
    assert d["road_edges"] == []
    assert d["front_road_width_m"] is None


def test_plot_area_falls_back_to_property_lines_as_model_source():
    m = model("compliant_house")
    m["site"]["plot_area_declared_m2"] = {"value": None, "source": "default"}
    pa = compute(m).values["plot_area_m2"]
    assert pa["value"] == pytest.approx(300.0) and pa["source"] == "model"


def test_unknown_counts_to_far_makes_fsi_unknown():
    m = model("compliant_house")
    m["areas"][0]["counts_to_far"] = {"value": None, "source": "default"}
    d = compute(m).values
    assert d["built_up_m2"] is None and d["far"] is None


def test_unknown_road_width_makes_front_road_unknown():
    m = model("compliant_house")
    m["site"]["edges"][0]["road_width_m"] = {"value": None, "source": "default"}
    assert compute(m).values["front_road_width_m"] is None


def test_inputs_for_maps_derived_paths_to_questions():
    assert "site.plot_area_declared_m2" in inputs_for("derived.far")
    assert inputs_for("derived.setback_m[e1]") == ["building.footprint", "site.edges"]
    assert inputs_for("site.edges[e1].road_width_m") == ["site.edges[e1].road_width_m"]
