"""Saving a project: rename, and the summaries the projects list shows (no login, so only ids the
caller already knows)."""

from fastapi.testclient import TestClient

from compliance.config import REPO_ROOT
from compliance.main import create_app


def test_rename_and_summaries_follow_what_was_saved(tmp_path):
    with TestClient(create_app(tmp_path / "p.sqlite")) as c:
        pid = c.post("/api/projects", json={"name": "demo_house"}).json()["id"]
        empty = c.get(f"/api/project-summaries?ids={pid},nope").json()
        assert [s["id"] for s in empty] == [pid]  # unknown ids are left out, never an error
        assert empty[0]["source_kind"] is None and empty[0]["last_check"] is None
        assert empty[0]["site"] == {"location": False, "plot": False, "sides": False}

        c.post(
            f"/api/projects/{pid}/dxf",
            content=(REPO_ROOT / "fixtures" / "dxf" / "demo_house.dxf").read_bytes(),
        )
        before = c.get(f"/api/project-summaries?ids={pid}").json()[0]
        assert before["source_kind"] == "dxf" and before["site"]["plot"] is True

        # Saving the site (no check) is what makes it "set".
        r = c.patch(
            f"/api/projects/{pid}/brief", json={"project.location": {"lat": 18.52, "lon": 73.84}}
        )
        assert r.status_code == 200
        after = c.get(f"/api/project-summaries?ids={pid}").json()[0]
        assert after["location"] == {"lat": 18.52, "lon": 73.84}
        assert after["site"]["location"] is True and after["updated_at"] >= before["updated_at"]

        assert (
            c.patch(f"/api/projects/{pid}", json={"name": "  Bungalow,   Baner  "}).json()["name"]
            == "Bungalow, Baner"
        )
        assert c.get(f"/api/projects/{pid}").json()["name"] == "Bungalow, Baner"
        assert c.patch(f"/api/projects/{pid}", json={"name": "   "}).status_code == 422
        assert c.patch("/api/projects/nope", json={"name": "x"}).status_code == 404
