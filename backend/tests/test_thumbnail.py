"""Axonometric card sketch (web samples, recent projects)."""

from pathlib import Path

from compliance.adapters import dxf
from compliance.thumbnail import plan_svg, worst_by_element

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sketch_marks_failures_red():
    model, _ = dxf.read(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf")
    plain = plan_svg(model)
    assert plain.startswith("<svg") and "var(--danger)" not in plain
    room = model["spaces"][0]["id"]
    report = {"results": [{"element": {"id": room}, "status": "pass"},
                          {"element": {"id": room}, "status": "fail"},
                          {"element": {"id": "e1"}, "status": "fail"}]}  # fmt: skip
    status = worst_by_element(report)
    assert status == {room: "fail", "e1": "fail"}
    assert plan_svg(model, status).count("var(--danger)") >= 2


def test_empty_model_is_still_an_svg():
    assert plan_svg({}).startswith("<svg")


def test_file_thumbnails_show_the_drawing_and_the_building():
    from compliance.adapters.dxf import drawing
    from compliance.adapters.mesh import ifc_to_mesh
    from compliance.thumbnail import floor_svg, mesh_png

    svg = floor_svg(drawing(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf"))
    assert svg and svg.startswith("<svg") and "var(--draw-wall)" in svg
    png = mesh_png(ifc_to_mesh(REPO_ROOT / "web" / "public" / "samples" / "demo_apartment.ifc"))
    assert png.startswith(b"\x89PNG") and len(png) > 2000
