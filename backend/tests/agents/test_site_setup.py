"""Site setup helpers: address suggestions as you type, and north read from the file."""

import math

import httpx
import pytest

from compliance.agents.authority import suggest
from compliance.config import REPO_ROOT

PHOTON_REPLY = {
    "features": [
        {
            "geometry": {"coordinates": [73.805668, 18.507262]},
            "properties": {
                "name": "Kothrud",
                "city": "Pune",
                "type": "locality",
                "extent": [73.78413, 18.522395, 73.8274981, 18.4920458],
            },
        },  # fmt: skip
        {
            "geometry": {"coordinates": [73.795247, 18.50652]},
            "properties": {
                "name": "Kothrud Depot",
                "street": "Paud Road",
                "city": "Pune",
                "type": "house",
            },
        },  # fmt: skip
        {  # the same place again under the same name: listed once
            "geometry": {"coordinates": [73.805668, 18.507262]},
            "properties": {"name": "Kothrud", "city": "Pune", "type": "locality"},
        },
    ]
}


def test_suggestions_are_bounded_to_the_city_and_say_area_or_address():
    seen = {}

    def reply(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=PHOTON_REPLY)

    places = suggest("kothrud", "pmc", http=httpx.Client(transport=httpx.MockTransport(reply)))
    assert seen["q"] == "kothrud" and len(seen["bbox"].split(",")) == 4
    assert [p["label"] for p in places] == ["Kothrud, Pune", "Kothrud Depot, Paud Road, Pune"]
    area, address = places
    assert area["precise"] is False
    w, s, e, n = area["extent"]
    assert w < e and s < n  # west, south, east, north
    assert address["precise"] is True and address["extent"] is None


def test_suggestions_for_an_unknown_city_are_refused():
    with pytest.raises(ValueError):
        suggest("kothrud", "nowhere")


@pytest.mark.parametrize("deg", [0.0, 30.0, -75.0])
def test_ifc_true_north_becomes_the_plan_rotation(tmp_path, deg):
    import ifcopenshell

    from compliance.adapters.ifc import north_deg

    src = REPO_ROOT / "fixtures" / "ifc" / "demo_house.ifc"
    f = ifcopenshell.open(str(src))
    ctx = next(
        c
        for c in f.by_type("IfcGeometricRepresentationContext")
        if not c.is_a("IfcGeometricRepresentationSubContext")
    )
    t = math.radians(deg)
    # north in model axes is (sin t, cos t) for a plan turned t anticlockwise (SiteMap.toGeo)
    ctx.TrueNorth = f.createIfcDirection((math.sin(t), math.cos(t)))
    path = tmp_path / "north.ifc"
    f.write(str(path))
    assert north_deg(path) == pytest.approx(deg, abs=0.01)


def test_dxf_geographic_location_gives_north(tmp_path):
    import ezdxf

    from compliance.adapters.dxf import north_deg

    doc = ezdxf.readfile(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf")
    assert north_deg(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf") is None
    geo = doc.modelspace().new_geodata()
    t = math.radians(20)
    geo.dxf.north_direction = (math.sin(t), math.cos(t))
    path = tmp_path / "geo.dxf"
    doc.saveas(path)
    assert north_deg(path) == pytest.approx(20, abs=0.01)


def test_orientation_route_reads_the_uploaded_drawing(tmp_path):
    import ezdxf
    from fastapi.testclient import TestClient

    from compliance.main import create_app

    doc = ezdxf.readfile(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf")
    doc.modelspace().new_geodata().dxf.north_direction = (0.0, 1.0)
    path = tmp_path / "geo.dxf"
    doc.saveas(path)
    with TestClient(create_app(tmp_path / "o.sqlite")) as c:
        pid = c.post("/api/projects", json={"name": "geo"}).json()["id"]
        assert c.get(f"/api/projects/{pid}/orientation").json()["rotation_deg"] is None
        c.post(f"/api/projects/{pid}/dxf", content=path.read_bytes())
        got = c.get(f"/api/projects/{pid}/orientation").json()
    assert got["rotation_deg"] == 0.0 and "geographic" in got["source"]
