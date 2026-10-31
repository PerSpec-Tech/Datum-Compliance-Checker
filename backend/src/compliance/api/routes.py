"""HTTP API. Errors are JSON {detail}; the Revit add-in shows `detail`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from compliance import files
from compliance.jobs import JobRunner, event_json
from compliance.retention import prune_versions
from compliance.schemas import errors as schema_errors
from compliance.store.repo import Store

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ dependencies


def store(request: Request) -> Store:
    return request.app.state.store


def runner(request: Request) -> JobRunner:
    return request.app.state.runner


def require_token(
    authorization: str | None = Header(default=None), st: Store = Depends(store)
) -> None:
    """Revit calls carry `Authorization: Bearer <token>` from pairing."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Pair this Revit with the web app first (Compliance › Pair).")
    if not st.check_token(authorization.split(" ", 1)[1].strip()):
        raise HTTPException(401, "This pairing is no longer valid. Pair again (Compliance › Pair).")


def project_or_404(project_id: str, st: Store) -> dict[str, Any]:
    p = st.get_project(project_id)
    if p is None:
        raise HTTPException(404, "Project not found.")
    st.touch_project(project_id)  # any use keeps the project's files (see retention)
    return p


def reads(request: Request):  # type: ignore[no-untyped-def]
    """The app's model-reading queue (ingest.ReadQueue)."""
    return request.app.state.reads


# A quick read answers the upload itself; a longer one carries on after the request (proxies such
# as Railway's cut requests that run for minutes) and the browser polls GET /reading for the end.
UPLOAD_WAIT_S = 20.0


async def _read_upload(request: Request, project_id: str, work: Any) -> Any:
    """Run work(saving), the queued read and storing its result, as a task of its own; answer
    with the result if it ends within UPLOAD_WAIT_S, else 202 {state: reading}. saving() marks
    the step after the read, so the status never falls back to idle in between."""
    import asyncio
    import logging

    from fastapi.responses import JSONResponse

    q = reads(request)
    running = q.tasks.get(project_id)
    if running is not None and not running.done():
        raise HTTPException(503, "A model for this project is already being read.")

    def saving() -> None:
        q.outcomes[project_id] = {"state": "reading", "pct": 98, "msg": "saving the model"}

    async def run() -> None:
        try:
            result = await work(saving)
            q.outcomes[project_id] = {"state": "done", "result": result}
        except HTTPException as e:
            q.outcomes[project_id] = {
                "state": "failed",
                "status": e.status_code,
                "detail": e.detail,
            }
        except Exception:  # noqa: BLE001 - reported to the browser, logged here
            logging.getLogger(__name__).exception("reading an upload failed")
            q.outcomes[project_id] = {
                "state": "failed",
                "status": 500,
                "detail": "Reading the model failed. Please try again.",
            }
        finally:
            q.tasks.pop(project_id, None)

    q.outcomes[project_id] = {"state": "queued", "ahead": 0, "reading": 0}
    task = asyncio.create_task(run())
    q.tasks[project_id] = task
    await asyncio.wait({task}, timeout=UPLOAD_WAIT_S)  # never cancels the read
    if not task.done():
        return JSONResponse({"state": "reading"}, status_code=202)
    end = q.outcomes.pop(project_id)
    if end["state"] == "failed":
        raise HTTPException(end["status"], end["detail"])
    return end["result"]


# ------------------------------------------------------------------ bodies


class PairComplete(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    device: str | None = None


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)


# ------------------------------------------------------------------ pairing


@router.post("/pair/start")
def pair_start(st: Store = Depends(store)) -> dict[str, Any]:
    return {"code": st.create_pair_code(), "expires_in_s": 600}


@router.post("/pair/complete")
def pair_complete(body: PairComplete, st: Store = Depends(store)) -> dict[str, str]:
    token = st.consume_pair_code(body.code, body.device)
    if token is None:
        raise HTTPException(
            400,
            "That pairing code is wrong, already used or expired. Get a new code in the web app.",
        )
    return {"token": token}


# ------------------------------------------------------------------ projects


@router.post("/projects")
def create_project(body: NewProject, st: Store = Depends(store)) -> dict[str, str]:
    return {"id": st.create_project(body.name)}


@router.get("/project-summaries")
def project_summaries(
    ids: str = Query(max_length=2000), st: Store = Depends(store)
) -> list[dict[str, Any]]:
    """A list of projects the caller already knows (by id): there is no login, so the server never
    lists everyone's projects. Unknown ids are left out."""
    wanted = [i for i in dict.fromkeys(ids.split(",")) if i][:50]
    return [s for i in wanted if (s := st.project_summary(i)) is not None]


@router.patch("/projects/{project_id}")
def rename_project(project_id: str, body: NewProject, st: Store = Depends(store)) -> dict[str, Any]:
    project_or_404(project_id, st)
    name = " ".join(body.name.split())[:120]
    if not name:
        raise HTTPException(422, "A project needs a name.")
    st.rename_project(project_id, name)
    return {"id": project_id, "name": name}


@router.get("/projects/{project_id}")
def get_project(project_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    p = project_or_404(project_id, st)
    latest = st.latest_model(project_id)
    report = st.db.one(
        "SELECT id FROM reports WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (project_id,),
    )
    return {
        **p,
        "latest_model_version": latest[0] if latest else None,
        "latest_report_id": report["id"] if report else None,
        "brief": st.get_brief(project_id),
    }


@router.get("/projects/{project_id}/model")
def get_project_model(project_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    """Latest model with the declared answers merged in (what the next check will see)."""
    from compliance.engine.brief import apply_brief

    project_or_404(project_id, st)
    latest = st.latest_model(project_id)
    if latest is None:
        raise HTTPException(404, "No model uploaded yet.")
    merged, skipped = apply_brief(latest[1], st.get_brief(project_id))
    return {"model_version": latest[0], "model": merged, "skipped_answers": skipped}


@router.get("/projects/{project_id}/thumbnail")
def get_thumbnail(project_id: str, st: Store = Depends(store)) -> Response:
    """What is in the file, for the project cards: a 2D drawing's ground-floor plan (SVG) or an
    IFC's building in 3D (PNG, cached). A model sent from Revit has neither: a sketch instead."""
    import json

    from compliance.thumbnail import floor_svg, plan_svg

    project_or_404(project_id, st)
    if (drawing_dir(project_id, st) / "drawing.dxf").exists():
        svg = floor_svg(json.loads(_drawing_json(project_id, st)))
        if svg:
            return Response(svg, media_type="image/svg+xml")
    latest = st.latest_model(project_id)
    if latest and (png := files.thumbnail(st, latest[0])) is not None:
        return Response(png.read_bytes(), media_type="image/png")
    model = get_project_model(project_id, st)["model"]
    return Response(plan_svg(model), media_type="image/svg+xml")


@router.get("/projects/{project_id}/suggestions")
def get_suggestions(
    project_id: str,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    st: Store = Depends(store),
) -> list[dict[str, Any]]:
    """Planning facts the checker can suggest, with what the model has now.

    `lat`/`lon` default to the project location. Confirming one is a PATCH /brief (declared).
    """
    from compliance.agents import planning

    model = get_project_model(project_id, st)["model"]
    loc = model["project"]["location"]["value"]
    if lat is None or lon is None:
        lat, lon = (loc["lat"], loc["lon"]) if loc else (None, None)
    site = planning.lookup(lat, lon, st) if lat is not None and lon is not None else None
    out = []
    for path, fact in planning.suggest(model, site).items():
        current = model["project"][path.removeprefix("project.")]
        out.append({"path": path, "suggested": fact, "current": current})
    return out


@router.get("/projects/{project_id}/live-pack")
def get_live_pack(project_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    """The latest check's limits as geometry for live mode in Revit / AutoCAD."""
    project_or_404(project_id, st)
    pack = st.get_live_pack(project_id)
    if pack is None:
        raise HTTPException(404, "Run a check first: the live pack comes from the latest check.")
    return pack


@router.get("/models/{version_id}/mesh")
async def get_mesh(version_id: str, request: Request, st: Store = Depends(store)) -> Any:
    """IFC geometry as triangles per element (by GlobalId) for the web viewer. Built when the
    model is uploaded and stored gzip-compressed; sent compressed (the browser unpacks it)."""
    gz = await _mesh_file(version_id, request, st)
    return Response(
        gz.read_bytes(), media_type="application/json", headers={"Content-Encoding": "gzip"}
    )


async def _mesh_file(version_id: str, request: Request, st: Store):  # type: ignore[no-untyped-def]
    import gzip
    import shutil

    from compliance import ingest

    folder = files.model_dir(st, version_id)
    gz = folder / ingest.MESH_GZ
    if gz.exists():
        return gz
    legacy = files.legacy_ifc(st, version_id)
    if legacy.exists():  # stored before per-version folders: move it in, compressed
        folder.mkdir(parents=True, exist_ok=True)
        with open(legacy, "rb") as raw, gzip.open(folder / ingest.IFC_GZ, "wb") as out:
            shutil.copyfileobj(raw, out)
        files.remove_model_files(st, version_id, keep_preview=True)
    if (folder / ingest.IFC_GZ).exists():
        try:
            await reads(request).run(
                f"mesh:{version_id}",
                lambda t: ingest.build_mesh(folder / ingest.IFC_GZ, folder, t),
            )
        except ingest.Busy as e:
            raise HTTPException(503, str(e)) from e
        except ingest.ReadFailed as e:
            raise HTTPException(422, str(e)) from e
        return gz
    model = st.get_model(version_id)
    if model is not None and model.get("meta", {}).get("source_kind") == "ifc":
        raise HTTPException(
            410,
            "The 3D view is removed after 30 days without use. Upload the model again to see it.",
        )
    raise HTTPException(404, "No IFC geometry for this model version.")


@router.put("/projects/{project_id}/model", dependencies=[Depends(require_token)])
def put_model(
    project_id: str, model: dict[str, Any] = Body(...), st: Store = Depends(store)
) -> dict[str, str]:
    project_or_404(project_id, st)
    errs = schema_errors("building-model.schema.json", model)
    if errs:
        raise HTTPException(
            422, "The model doesn't match the BuildingModel contract: " + "; ".join(errs[:5])
        )
    version = st.add_model_version(project_id, model)
    prune_versions(st, project_id)
    return {"model_version": version}


def _max_bytes() -> int:
    from compliance.config import get_settings

    return get_settings().max_upload_mb * 1024 * 1024


def _too_large(kind: str) -> HTTPException:
    from compliance.config import get_settings

    mb = get_settings().max_upload_mb
    return HTTPException(413, f"{kind} up to {mb} MB can be checked in the web app.")


def drawing_dir(project_id: str, st: Store):  # type: ignore[no-untyped-def]
    """A project's uploaded DXF and its layer → role mapping."""
    return files.drawing_dir(st, project_id)


def _read_drawing(project_id: str, st: Store, llm: Any = None) -> dict[str, Any]:
    """Read the stored DXF with the project's layer roles; store the result as a model version.
    With `llm`, unknown layers first get Nemotron's suggested roles."""
    import json

    from compliance.adapters.dxf import layer_profiles, layer_report
    from compliance.adapters.dxf import read as read_dxf

    folder = drawing_dir(project_id, st)
    path = folder / "drawing.dxf"
    roles_file, sugg_file = folder / "roles.json", folder / "suggested.json"
    roles = json.loads(roles_file.read_text("utf-8")) if roles_file.exists() else {}
    suggested = json.loads(sugg_file.read_text("utf-8")) if sugg_file.exists() else {}
    if llm is not None:
        from compliance.agents.layers import suggest_roles

        try:
            new = suggest_roles(layer_profiles(path, {**_roles(suggested), **roles}), llm)
        except Exception:  # noqa: BLE001 - suggestions are optional; the table still works
            new = {}
        if new:
            suggested.update(new)
            sugg_file.write_text(json.dumps(suggested, indent=2), encoding="utf-8")
    merged = {**_roles(suggested), **roles}
    try:
        model, warnings = read_dxf(path, merged)
        layers = layer_report(path, roles, suggested)
    except Exception as e:  # noqa: BLE001 - any parser failure is the file's problem
        raise HTTPException(422, f"Couldn't read this DXF file: {e}") from e
    project = st.get_project(project_id) or {}
    model["project"]["name"] = project.get("name") or model["project"]["name"]
    errs = schema_errors("building-model.schema.json", model)
    if errs:
        raise HTTPException(
            422, "The drawing converted to an invalid model: " + "; ".join(errs[:3])
        )
    version = st.add_model_version(project_id, model)
    prune_versions(st, project_id)
    return {
        "model_version": version,
        "warnings": warnings,
        "counts": {
            k: len(model[k]) for k in ("levels", "spaces", "areas", "stairs", "doors", "units")
        },
        "has_site_boundary": model["site"]["boundary"] is not None,
        "layers": layers,
        "unmapped": sum(1 for x in layers if x["role"] is None),
    }


def _roles(suggested: dict[str, Any]) -> dict[str, str]:
    return {k: v["role"] for k, v in suggested.items()}


@router.post("/projects/{project_id}/dxf")
async def upload_dxf(
    project_id: str, request: Request, st: Store = Depends(store)
) -> dict[str, Any]:
    """Body: the raw .dxf file. 2D drawings in the PreDCR layer standard read directly;
    other layer names can be mapped with PUT /dxf/roles. DWG: save as DXF first."""
    import asyncio

    project_or_404(project_id, st)
    data = await request.body()
    if not data:
        raise HTTPException(400, "Send the .dxf file as the request body.")
    if len(data) > _max_bytes():
        raise _too_large("Drawings")
    if data[:6] == b"AC1032" or data[:4] == b"AC10":
        raise HTTPException(415, "That's a DWG file. In AutoCAD use Save As → DXF, then upload it.")
    if b"SECTION" not in data[:2000]:
        raise HTTPException(415, "That doesn't look like a DXF file.")
    folder = drawing_dir(project_id, st)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "drawing.dxf").write_bytes(data)
    llm = getattr(request.app.state, "llm", None)

    async def job(t: Any) -> dict[str, Any]:
        t.pct, t.msg = 10, "reading the drawing"
        return await asyncio.to_thread(_read_drawing, project_id, st, llm)

    from compliance.ingest import Busy

    async def work(saving: Any) -> dict[str, Any]:
        try:
            return await reads(request).run(project_id, job)
        except Busy as e:
            raise HTTPException(503, str(e)) from e

    return await _read_upload(request, project_id, work)


@router.get("/projects/{project_id}/drawing")
def get_drawing(project_id: str, st: Store = Depends(store)) -> Any:
    """The uploaded DXF as vector data per floor plan, aligned with the model (web plan view)."""
    project_or_404(project_id, st)
    return Response(_drawing_json(project_id, st), media_type="application/json")


@router.get("/projects/{project_id}/drawing/frames")
def get_drawing_frames(project_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    """Each floor plan's frame and alignment shift, and the layer roles (AutoCAD live)."""
    import json

    from compliance.adapters.dxf import frames

    project_or_404(project_id, st)
    folder = drawing_dir(project_id, st)
    path = folder / "drawing.dxf"
    if not path.exists():
        raise HTTPException(404, "This project has no 2D drawing.")
    roles = {}
    if (folder / "suggested.json").exists():
        roles = _roles(json.loads((folder / "suggested.json").read_text("utf-8")))
    if (folder / "roles.json").exists():
        roles |= json.loads((folder / "roles.json").read_text("utf-8"))
    return frames(path, roles)


def _drawing_json(project_id: str, st: Store) -> bytes:
    import json

    from compliance.adapters.dxf import drawing

    folder = drawing_dir(project_id, st)
    path = folder / "drawing.dxf"
    if not path.exists():
        raise HTTPException(404, "This project has no 2D drawing.")
    sources = [path, folder / "roles.json", folder / "suggested.json"]
    stamp = "-".join(str(int(f.stat().st_mtime)) for f in sources if f.exists())
    cache = folder / f"drawing.{stamp}.json"
    if not cache.exists():
        roles = (
            json.loads((folder / "roles.json").read_text("utf-8"))
            if (folder / "roles.json").exists()
            else {}
        )
        sugg_file = folder / "suggested.json"
        suggested = json.loads(sugg_file.read_text("utf-8")) if sugg_file.exists() else {}
        data = drawing(path, {**_roles(suggested), **roles})
        for old in folder.glob("drawing.*.json"):
            old.unlink()
        cache.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return cache.read_bytes()


@router.put("/projects/{project_id}/dxf/roles")
async def set_dxf_roles(
    project_id: str, roles: dict[str, str | None] = Body(...), st: Store = Depends(store)
) -> dict[str, Any]:
    """Map drawing layers to roles ({layer: role}), then re-read the drawing."""
    import asyncio
    import json

    project_or_404(project_id, st)
    folder = drawing_dir(project_id, st)
    if not (folder / "drawing.dxf").exists():
        raise HTTPException(404, "Upload a DXF for this project first.")
    allowed = {"plot", "road", "footprint", "floor", "floor_height", "ground", "fsi_resi",
               "fsi_comm", "fsi_other", "carpet", "room", "door", "window", "stair", "balcony",
               "parking", "ignore"}  # fmt: skip
    bad = sorted({r for r in roles.values() if r is not None and r not in allowed})
    if bad:
        raise HTTPException(422, f"Unknown layer roles: {', '.join(bad)}")
    path = folder / "roles.json"
    current = json.loads(path.read_text("utf-8")) if path.exists() else {}
    current.update({k: v for k, v in roles.items() if v is not None})
    for k, v in roles.items():
        if v is None:
            current.pop(k, None)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return await asyncio.to_thread(_read_drawing, project_id, st)


@router.post("/projects/{project_id}/ifc")
async def upload_ifc(
    project_id: str, request: Request, st: Store = Depends(store)
) -> dict[str, Any]:
    """Body: the raw .ifc file (any content type). Converted by the IFC adapter."""
    import shutil
    import tempfile
    from pathlib import Path

    from compliance import ingest

    project_or_404(project_id, st)
    data = await request.body()
    if not data:
        raise HTTPException(400, "Send the .ifc file as the request body.")
    if len(data) > _max_bytes():
        raise _too_large("IFC files")
    if b"ISO-10303-21" not in data[:200]:
        raise HTTPException(415, "That doesn't look like an IFC (STEP) file.")
    staging = files.root(st) / "tmp"
    staging.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=staging))
    src, out = tmp / "upload.ifc", tmp / "out"
    src.write_bytes(data)
    del data  # the child reads the file; don't hold a second copy while it does

    async def work(saving: Any) -> dict[str, Any]:
        try:
            try:
                model, warnings = await reads(request).run(
                    project_id, lambda t: ingest.read_ifc(src, out, t)
                )
            except ingest.Busy as e:
                raise HTTPException(503, str(e)) from e
            except ingest.ReadFailed as e:
                raise HTTPException(422, str(e)) from e
            saving()
            errs = schema_errors("building-model.schema.json", model)
            if errs:
                raise HTTPException(
                    422, "The IFC converted to an invalid model: " + "; ".join(errs[:3])
                )
            version = st.add_model_version(project_id, model)
            target = files.model_dir(st, version)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(target))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        prune_versions(st, project_id)
        return {
            "model_version": version,
            "warnings": warnings,
            "counts": {
                k: len(model[k]) for k in ("levels", "spaces", "areas", "stairs", "doors", "units")
            },
            "has_site_boundary": model["site"]["boundary"] is not None,
        }

    return await _read_upload(request, project_id, work)


@router.get("/projects/{project_id}/reading")
def reading_status(project_id: str, request: Request) -> dict[str, Any]:
    """Where this project's upload is: {state: queued, ahead, reading}, {state: reading, pct,
    msg}, then {state: done, result} (what the upload would have answered) or {state: failed,
    status, detail}; {state: idle} when there is nothing. Polled by the web app."""
    return reads(request).status(project_id) or {"state": "idle"}


@router.get("/models/{version_id}/ifc")
def get_ifc(version_id: str, st: Store = Depends(store)):
    """The uploaded IFC, for the web 3D viewer."""
    from fastapi.responses import FileResponse

    from compliance.ingest import IFC_GZ

    gz = files.model_dir(st, version_id) / IFC_GZ
    if gz.exists():  # stored compressed: sent as is, the browser unpacks it
        return FileResponse(
            gz,
            media_type="application/x-step",
            filename="model.ifc",
            headers={"Content-Encoding": "gzip"},
        )
    path = files.legacy_ifc(st, version_id)
    if not path.exists():
        raise HTTPException(404, "No IFC file for this model version.")
    return FileResponse(path, media_type="application/x-step", filename="model.ifc")


@router.patch("/projects/{project_id}/brief")
def patch_brief(
    project_id: str, answers: dict[str, Any] = Body(...), st: Store = Depends(store)
) -> dict[str, Any]:
    project_or_404(project_id, st)
    st.set_brief(project_id, answers)
    return {"brief": st.get_brief(project_id)}


# ------------------------------------------------------------------ checks & jobs


@router.post("/projects/{project_id}/checks")
async def start_check(
    project_id: str, st: Store = Depends(store), jr: JobRunner = Depends(runner)
) -> dict[str, str]:
    project_or_404(project_id, st)
    latest = st.latest_model(project_id)
    if latest is None:
        raise HTTPException(409, "Upload a model before running a check.")
    return {"job_id": jr.start(project_id, latest[0])}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    job = st.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, st: Store = Depends(store), jr: JobRunner = Depends(runner)
) -> EventSourceResponse:
    job = st.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")

    async def stream():
        if jr.bus.known(job_id):
            async for e in jr.bus.subscribe(job_id):
                yield {"data": event_json(e)}
            return
        # Job from before a restart: report its final state once.
        if job["status"] == "done":
            yield {"data": event_json({"stage": "done", "pct": 100, "report_id": job["report_id"]})}
        else:
            msg = job["error"] or "This check was interrupted. Run it again."
            yield {"data": event_json({"stage": "error", "error": msg, "msg": msg})}

    return EventSourceResponse(stream(), ping=15)


# ------------------------------------------------------------------ reports


@router.get("/reports/{report_id}")
def get_report(report_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    r = st.get_report(report_id)
    if r is None:
        raise HTTPException(404, "Report not found.")
    return r


@router.get("/reports/{report_id}/bcf")
def get_bcf(report_id: str, st: Store = Depends(store)):
    """BCF 2.1 zip with one topic per failure."""
    from fastapi.responses import Response

    from compliance.adapters.bcf import export

    report = st.get_report(report_id)
    if report is None:
        raise HTTPException(404, "Report not found.")
    model = st.get_model(report["model_version"]) or {}
    project = st.get_project(report["project_id"]) or {"name": "project"}
    data = export(
        report,
        source_kind=(model.get("meta") or {}).get("source_kind", "manual"),
        project_name=project["name"],
    )
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="compliance-{report_id[:8]}.bcfzip"'
        },
    )


# ------------------------------------------------------------------ rules & usage


@router.get("/rules")
def list_rules(request: Request) -> list[dict[str, Any]]:
    rb = request.app.state.rulebase()
    return [_rule_summary(r) for r in sorted(rb.rules.values(), key=lambda r: (r.ruleset, r.id))]


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str, request: Request) -> dict[str, Any]:
    rb = request.app.state.rulebase()
    if rule_id not in rb.rules:
        raise HTTPException(404, "Rule not found.")
    r = rb.rules[rule_id]
    tables = {t: rb.tables[t] for c in r.exprs.values() for t in c.tables}
    return {**_rule_summary(r), "doc": r.doc, "tables": tables}


class CompileRequest(BaseModel):
    clause_text: str = Field(min_length=20, max_length=6000)
    clause_ref: str = Field(min_length=1, max_length=80)
    source: str = Field(default="pasted by user", max_length=300)
    authority: str = Field(default="udcpr2020", pattern=r"^[a-z0-9_]+$")
    review: bool = False


@router.post("/rules/compile")
def compile_rule(body: CompileRequest, request: Request) -> dict[str, Any]:
    """Live demo of the rule compiler: returns a checked draft; nothing is saved."""
    from compliance.agents.compiler import Clause, compile_clause

    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(503, "The rule compiler needs NEBIUS_API_KEY on the server.")
    clause = Clause(body.clause_text, body.clause_ref, body.source, body.authority)
    return compile_clause(clause, llm, request.app.state.rulebase(), review=body.review).as_dict()


@router.get("/cities")
def cities() -> list[dict[str, Any]]:
    """Supported planning authorities (the web app's city step)."""
    from compliance.agents.authority import authorities

    out = []
    for a in authorities():
        b = a.get("bbox") or {}
        center = (
            {"lat": (b["south"] + b["north"]) / 2, "lon": (b["west"] + b["east"]) / 2}
            if b
            else None
        )
        city = (a.get("match") or {}).get("city", [a["name"]])[0]
        out.append({"id": a["id"], "city": city, "authority": a["name"], "center": center})
    return out


@router.get("/geocode")
def geocode(
    q: str = Query(min_length=3, max_length=200), authority: str = "pmc", st: Store = Depends(store)
) -> list[dict[str, Any]]:
    import httpx

    from compliance.agents.authority import search

    try:
        return search(q, authority, st)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            502, "Address search is unavailable right now. Drop a pin instead."
        ) from e


@router.get("/suggest")
def suggest(
    q: str = Query(min_length=3, max_length=200), authority: str = "pmc", st: Store = Depends(store)
) -> list[dict[str, Any]]:
    """Address suggestions as you type (site setup), with each area's extent for the map."""
    import httpx

    from compliance.agents.authority import suggest as photon

    try:
        return photon(q, authority, st)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            502, "Suggestions are unavailable right now. Press Enter to search."
        ) from e


@router.get("/projects/{project_id}/orientation")
def orientation(project_id: str, st: Store = Depends(store)) -> dict[str, Any]:
    """North as the file states it (IFC TrueNorth, or a DXF's geographic location), so the site
    setup can skip turning the plan by hand. rotation_deg is null when the file doesn't say."""
    import json

    from compliance.adapters import dxf, ifc

    project_or_404(project_id, st)
    drawing = drawing_dir(project_id, st) / "drawing.dxf"
    latest = st.latest_model(project_id)
    deg, source = None, None
    try:
        if drawing.exists():
            deg, source = dxf.north_deg(drawing), "the drawing's geographic location"
        elif latest is not None and (meta := files.meta(st, latest[0])).exists():
            deg = json.loads(meta.read_text("utf-8")).get("north_deg")
            source = "the IFC's true north"
        elif latest is not None and (path := files.legacy_ifc(st, latest[0])).exists():
            deg, source = ifc.north_deg(path), "the IFC's true north"
    except Exception:  # noqa: BLE001 - an unreadable north is just not known
        deg = None
    return {"rotation_deg": deg, "source": source if deg is not None else None}


@router.get("/locate")
def locate(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    st: Store = Depends(store),
) -> dict[str, Any]:
    """Which authority covers this point, and a short place label (map pin feedback)."""
    from compliance.agents.authority import place_label, resolve

    r = resolve(lat, lon, st)
    return {"authority_id": r.authority_id, "note": r.note, "label": place_label(lat, lon, st)}


@router.get("/usage")
def usage(st: Store = Depends(store)) -> dict[str, Any]:
    return st.usage_summary()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    rb = request.app.state.rulebase()
    return {"ok": True, "rules": len(rb.rules), "ruleset_version": rb.version}


def _rule_summary(r) -> dict[str, Any]:
    d = r.doc
    return {
        "id": r.id,
        "title": d["title"],
        "ruleset": r.ruleset,
        "kind": r.kind,
        "severity": d["severity"],
        "status": d["status"],
        "clause": d["clause"],
        "for_each": d.get("for_each"),
        "expressions": {
            k: d[k] for k in ("applies_when", "limit", "measured", "check") if d.get(k)
        },
        "compiled_by": d["compiled_by"],
        "freshness": d.get("freshness"),
        "requires": sorted(r.requires),
    }
