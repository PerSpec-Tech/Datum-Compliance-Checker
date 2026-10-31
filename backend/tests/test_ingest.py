"""Model reading queue, single-pass uploads and retention."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from compliance import files, ingest
from compliance.config import REPO_ROOT
from compliance.main import create_app
from compliance.retention import sweep

IFC = REPO_ROOT / "fixtures" / "ifc" / "violating_apartment.ifc"


# ------------------------------------------------------------------ queue


def test_queue_runs_in_arrival_order_within_its_slots():
    async def scenario():
        q = ingest.ReadQueue(slots=1, max_waiting=5)
        gate, order, seen = asyncio.Event(), [], {}

        async def job(name: str, t: ingest.Ticket):
            order.append(name)
            if name == "a":
                await gate.wait()
            return name

        a = asyncio.create_task(q.run("a", lambda t: job("a", t)))
        await asyncio.sleep(0)
        b = asyncio.create_task(q.run("b", lambda t: job("b", t)))
        c = asyncio.create_task(q.run("c", lambda t: job("c", t)))
        await asyncio.sleep(0.01)
        seen["a"], seen["b"], seen["c"] = q.status("a"), q.status("b"), q.status("c")
        with pytest.raises(ingest.Busy):  # one read per project at a time
            await q.run("b", lambda t: job("b", t))
        gate.set()
        assert await asyncio.gather(a, b, c) == ["a", "b", "c"]
        return order, seen, q.status("a")

    order, seen, after = asyncio.run(scenario())
    assert order == ["a", "b", "c"]
    assert seen["a"]["state"] == "reading"
    assert seen["b"] == {"state": "queued", "ahead": 0, "reading": 1}
    assert seen["c"] == {"state": "queued", "ahead": 1, "reading": 1}
    assert after is None


def test_queue_turns_away_uploads_when_the_line_is_full():
    async def scenario():
        q = ingest.ReadQueue(slots=1, max_waiting=1)
        gate = asyncio.Event()

        async def hold(t):
            await gate.wait()

        first = asyncio.create_task(q.run("a", hold))
        await asyncio.sleep(0)
        second = asyncio.create_task(q.run("b", hold))
        await asyncio.sleep(0.01)
        with pytest.raises(ingest.Busy, match="busy"):
            await q.run("c", hold)
        gate.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())


# ------------------------------------------------------------------ upload and retention


def test_upload_stores_compressed_files_once_and_keeps_only_the_latest_version(tmp_path):
    app = create_app(tmp_path / "r.sqlite")
    data = IFC.read_bytes()
    with TestClient(app) as c:
        st = app.state.store
        pid = c.post("/api/projects", json={"name": "IFC"}).json()["id"]
        first = c.post(f"/api/projects/{pid}/ifc", content=data).json()["model_version"]
        folder = files.model_dir(st, first)
        assert {p.name for p in folder.iterdir()} >= {ingest.IFC_GZ, ingest.MESH_GZ, ingest.META}
        assert c.get(f"/api/models/{first}/mesh").json()["spaces"]
        assert c.get(f"/api/projects/{pid}/reading").json() == {"state": "idle"}

        second = c.post(f"/api/projects/{pid}/ifc", content=data).json()["model_version"]
        assert st.model_versions(pid) == [second]
        assert not folder.exists()


def test_sweep_expires_files_after_30_days_and_projects_after_90(tmp_path):
    app = create_app(tmp_path / "s.sqlite")
    data = IFC.read_bytes()
    with TestClient(app) as c:
        st = app.state.store
        old = c.post("/api/projects", json={"name": "old"}).json()["id"]
        idle = c.post("/api/projects", json={"name": "idle"}).json()["id"]
        fresh = c.post("/api/projects", json={"name": "fresh"}).json()["id"]
        versions = {
            p: c.post(f"/api/projects/{p}/ifc", content=data).json()["model_version"]
            for p in (old, idle, fresh)
        }
        for pid, days in ((old, 91), (idle, 31)):
            st.db.execute(
                "UPDATE projects SET last_opened_at = datetime('now', ?) WHERE id = ?",
                (f"-{days} days", pid),
            )
        out = sweep(st)

        assert out["projects_deleted"] == 1 and st.get_project(old) is None
        assert not files.model_dir(st, versions[old]).exists()

        assert not files.has_ifc(st, versions[idle])
        assert files.thumbnail(st, versions[idle]) is not None  # the card still has a picture
        r = c.get(f"/api/models/{versions[idle]}/mesh")
        assert r.status_code == 410 and "Upload the model again" in r.json()["detail"]
        assert c.get(f"/api/projects/{idle}/model").status_code == 200  # reports keep working

        assert files.has_ifc(st, versions[fresh])


def test_a_long_read_carries_on_after_the_upload_answers(tmp_path, monkeypatch):
    import time

    from compliance.api import routes

    monkeypatch.setattr(routes, "UPLOAD_WAIT_S", 0.0)  # every read counts as long
    app = create_app(tmp_path / "l.sqlite")
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "long"}).json()["id"]
        r = c.post(f"/api/projects/{pid}/ifc", content=IFC.read_bytes())
        assert r.status_code == 202 and r.json() == {"state": "reading"}
        assert c.post(f"/api/projects/{pid}/ifc", content=IFC.read_bytes()).status_code == 503
        for _ in range(240):
            s = c.get(f"/api/projects/{pid}/reading").json()
            assert s["state"] in ("queued", "reading", "done"), s
            if s["state"] == "done":
                break
            time.sleep(0.25)
        assert s["result"]["counts"]["spaces"] > 0
        assert c.get(f"/api/models/{s['result']['model_version']}/mesh").status_code == 200

        bad = c.post(f"/api/projects/{pid}/ifc", content=b"ISO-10303-21;\nnot really")
        assert bad.status_code == 202
        for _ in range(240):
            s = c.get(f"/api/projects/{pid}/reading").json()
            if s["state"] == "failed":
                break
            time.sleep(0.25)
        assert s["status"] == 422 and "Couldn't read" in s["detail"]
