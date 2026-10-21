"""FastAPI app (P4.2). Run locally with `just dev-backend`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from compliance.api.routes import router
from compliance.config import get_settings
from compliance.engine.rules import RuleBase, load_rulebase
from compliance.jobs import JobRunner
from compliance.llm.client import LLMClient
from compliance.store.db import Database
from compliance.store.repo import Store


def create_app(
    db_path: Path | str | None = None,
    *,
    rules_dir: Path | None = None,
    runner_factory: Callable[[Store, Callable[[], RuleBase]], JobRunner] | None = None,
) -> FastAPI:
    settings = get_settings()
    store = Store(Database(db_path or settings.app_db_path))
    rules = load_rulebase(rules_dir)  # fail fast on a broken rule file

    def rulebase() -> RuleBase:
        return rules

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Jobs need the running event loop, so the runner is created here.
        app.state.runner = (runner_factory or _default_runner)(store, rulebase)
        yield

    app = FastAPI(title="Compliance Checker", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.rulebase = rulebase
    app.state.llm = LLMClient(store) if settings.nebius_api_key else None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # the web app may be served from another origin during development
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    _serve_web(app)
    return app


def _serve_web(app: FastAPI) -> None:
    """Serve the built web app (web/dist) from the same origin, with SPA fallback (P7.1)."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from compliance.config import REPO_ROOT

    dist = REPO_ROOT / "web" / "dist"
    if not (dist / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        file = dist / path
        if path and file.is_file() and dist in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(dist / "index.html")


def _default_runner(store: Store, rulebase: Callable[[], RuleBase]) -> JobRunner:
    """Real pipeline: Nemotron (and Tavily, when keys are set) plugged in as stage hooks."""
    from compliance.agents.hooks import make_hooks
    from compliance.search.tavily import Search

    discover = None
    if get_settings().tavily_api_key:
        search = Search(store)

        def discover(place: str) -> list[dict]:
            """Official sources only: Indian government sites (gov.in / nic.in)."""
            results = search.search(
                f"{place} development control regulations building bye-laws notification PDF",
                domains=["gov.in", "nic.in"],
                max_results=8,
            )
            official = (".gov.in", ".nic.in")
            return [
                r for r in results
                if any(urlparse(r["url"]).hostname.endswith(d) for d in official)
            ][:5]  # fmt: skip

    return JobRunner(store, rulebase, hooks=make_hooks(store), discover=discover)


def app() -> FastAPI:  # uvicorn --factory compliance.main:app
    return create_app()
