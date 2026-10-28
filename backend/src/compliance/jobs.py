"""Check jobs: one asyncio task per job, running the §3 pipeline and streaming progress.

resolve_authority → overlays → classify_usage → derive → evaluate → freshness → plan_questions →
explain → done. The deterministic engine decides every status; agent stages (classify, freshness,
explain) are optional hooks that only add inferred facts, freshness flags or wording. A hook that
fails is reported and skipped — it never fails the check.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from compliance.agents import planning
from compliance.agents.authority import Resolution, resolve
from compliance.agents.overlays import apply_overlays
from compliance.engine.brief import apply_brief
from compliance.engine.live import build_live_pack
from compliance.engine.report import build_report
from compliance.engine.rules import RuleBase
from compliance.store.repo import Store

log = logging.getLogger(__name__)

STAGES = (
    "resolve_authority",
    "overlays",
    "classify_usage",
    "derive",
    "evaluate",
    "freshness",
    "plan_questions",
    "explain",
)


class JobError(Exception):
    """The check can't continue (e.g. no location to find the planning authority)."""


@dataclass
class JobContext:
    job_id: str
    project_id: str
    model_version_id: str
    model: dict[str, Any]
    rulebase: RuleBase
    report: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


# A hook takes the context, may change ctx.model (before evaluate) or ctx.report (after), and
# returns a short message for the progress stream.
Hook = Callable[[JobContext], str | None]


class JobBus:
    """Per-job event history plus live fan-out, so late SSE subscribers still see everything."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._cond: dict[str, asyncio.Condition] = {}

    def open(self, job_id: str) -> None:
        self._events[job_id] = []
        self._cond[job_id] = asyncio.Condition()

    def known(self, job_id: str) -> bool:
        return job_id in self._events

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        cond = self._cond[job_id]
        async with cond:
            self._events[job_id].append(event)
            cond.notify_all()

    async def subscribe(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        cond, seen = self._cond[job_id], 0
        while True:
            async with cond:
                while seen >= len(self._events[job_id]):
                    await cond.wait()
                batch = self._events[job_id][seen:]
                seen += len(batch)
            for e in batch:
                yield e
                if e["stage"] in ("done", "error"):
                    return


class JobRunner:
    def __init__(
        self,
        store: Store,
        rulebase: Callable[[], RuleBase],
        *,
        resolver: Callable[..., Resolution] = resolve,
        hooks: dict[str, Hook] | None = None,
        discover: Callable[[str], list[dict[str, Any]]] | None = None,
        site_lookup: Callable[[float, float], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.rulebase = rulebase
        self.resolver = resolver
        self.hooks = hooks or {}
        self.discover = discover  # Tavily lookup of rule documents for places we don't cover yet
        self.site_lookup = site_lookup  # locality + land use at the pin (planning suggestions)
        self.bus = JobBus()
        self._tasks: set[asyncio.Task] = set()

    def start(self, project_id: str, model_version_id: str) -> str:
        job_id = self.store.create_job(project_id, model_version_id)
        self.bus.open(job_id)
        task = asyncio.create_task(self._run(job_id, project_id, model_version_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job_id

    async def _emit(
        self, job_id: str, stage: str, pct: float, msg: str | None = None, **extra: Any
    ) -> None:
        self.store.update_job(job_id, stage=stage, pct=pct, message=msg)
        await self.bus.publish(job_id, {"stage": stage, "pct": round(pct), "msg": msg, **extra})

    async def _run(self, job_id: str, project_id: str, version_id: str) -> None:
        stage = "queued"
        try:
            self.store.update_job(job_id, status="running")
            model = self.store.get_model(version_id)
            if model is None:
                raise JobError("the model version was not found")
            model, skipped = apply_brief(model, self.store.get_brief(project_id))
            ctx = JobContext(job_id, project_id, version_id, model, self.rulebase())
            if skipped:
                ctx.notes.append(
                    f"{len(skipped)} saved answer(s) no longer match the model and were skipped"
                )

            for i, stage in enumerate(STAGES):
                pct = 5 + 90 * i / len(STAGES)
                await self._emit(job_id, stage, pct, _STAGE_LABEL[stage])
                msg = await asyncio.to_thread(self._stage, stage, ctx)
                if msg:
                    await self._emit(job_id, stage, pct + 90 / len(STAGES) * 0.8, msg)

            assert ctx.report is not None
            self.store.save_report(ctx.report)
            try:  # the live pack for the add-ins; it never fails the check itself
                pack = await asyncio.to_thread(build_live_pack, ctx.model, ctx.rulebase, ctx.report)
                self.store.save_live_pack(project_id, pack)
            except Exception:  # noqa: BLE001
                log.exception("live pack for %s failed", project_id)
            self.store.update_job(job_id, status="done", report_id=ctx.report["id"])
            s = ctx.report["summary"]
            await self._emit(
                job_id,
                "done",
                100,
                f"{s['fail']} fail · {s['unverifiable']} cannot verify · {s['pass']} pass",
                report_id=ctx.report["id"],
            )
        except Exception as e:  # noqa: BLE001 - any failure ends the job with a readable error
            msg = str(e) if isinstance(e, JobError) else f"{type(e).__name__}: {e}"
            if not isinstance(e, JobError):
                log.exception("job %s failed in %s", job_id, stage)
            self.store.update_job(job_id, status="error", stage=stage, error=msg)
            with contextlib.suppress(Exception):
                await self.bus.publish(
                    job_id,
                    {
                        "stage": "error",
                        "pct": None,
                        "msg": msg,
                        "error": msg,
                        "failed_stage": stage,
                    },
                )

    # ------------------------------------------------------------------ stages (run in a thread)

    def _stage(self, stage: str, ctx: JobContext) -> str | None:
        if stage == "resolve_authority":
            return self._resolve_authority(ctx)
        if stage == "overlays":
            loc = ctx.model["project"]["location"]["value"]
            site = self.site_lookup(loc["lat"], loc["lon"]) if self.site_lookup and loc else None
            msgs = (apply_overlays(ctx.model, ctx.rulebase), planning.apply(ctx.model, site))
            return "; ".join(m for m in msgs if m) or None
        if stage == "evaluate":
            ctx.report = build_report(
                ctx.model,
                ctx.rulebase,
                project_id=ctx.project_id,
                model_version=ctx.model_version_id,
            )
            s = ctx.report["summary"]
            n = len(ctx.report["results"])
            return f"{n} results: {s['fail']} fail, {s['unverifiable']} cannot verify"
        if stage == "derive":
            return None  # computed inside evaluate; kept as a visible step
        if stage == "plan_questions":
            n = len(ctx.report["questions"]) if ctx.report else 0
            return (
                f"{n} question{'s' if n != 1 else ''} to unlock more checks"
                if n
                else "nothing missing"
            )
        hook = self.hooks.get(stage)
        if hook is None:
            return None
        try:
            return hook(ctx)
        except Exception as e:  # noqa: BLE001 - agent stages are best-effort
            log.warning("stage %s skipped: %s", stage, e)
            return f"skipped: {e}"

    def _resolve_authority(self, ctx: JobContext) -> str:
        project = ctx.model["project"]
        if project["rulesets"]["value"]:
            return f"using {project['authority_id']['value'] or 'given'} rules: " + ", ".join(
                project["rulesets"]["value"]
            )
        loc = project["location"]["value"]
        if not loc:
            raise JobError(
                "The project location is missing. Set it in Site Setup so the planning "
                "authority can be found."
            )
        res = self.resolver(loc["lat"], loc["lon"], self.store)
        if not res.rulesets:
            raise JobError(
                f"No rules for this location: {res.note}. Check the project location in Site Setup."
                + self._discovered(res)
            )
        project["authority_id"] = {
            "value": res.authority_id,
            "source": "inferred",
            "note": res.note,
        }
        project["rulesets"] = {"value": res.rulesets, "source": "inferred", "note": res.note}
        return res.note

    def _discovered(self, res: Resolution) -> str:
        """Courtesy for places we don't cover: official rule documents found with Tavily."""
        place = res.address.get("city") or res.address.get("town") or res.address.get("state")
        if not (self.discover and place):
            return ""
        try:
            docs = self.discover(place)[:3]
        except Exception as e:  # noqa: BLE001 - discovery never blocks the error message
            log.warning("discovery failed: %s", e)
            return ""
        if not docs:
            return ""
        return " Official rule documents found for this place: " + "; ".join(
            f"{d['title'] or d['url']} ({d['url']})" for d in docs
        )


_STAGE_LABEL = {
    "resolve_authority": "Finding the planning authority…",
    "overlays": "Checking the site: metro TOD, land use, building type…",
    "classify_usage": "Classifying room uses…",
    "derive": "Measuring the model…",
    "evaluate": "Checking the rules…",
    "freshness": "Checking for amendments…",
    "plan_questions": "Working out what's missing…",
    "explain": "Writing the summary…",
}


def event_json(event: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in event.items() if v is not None})
