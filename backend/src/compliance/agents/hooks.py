"""Wires the Nemotron / Tavily agents into the job pipeline as best-effort stage hooks."""

from __future__ import annotations

from compliance.agents.classify import classify_spaces
from compliance.agents.explain import explain
from compliance.agents.freshness import apply_to_report
from compliance.agents.questions_text import reword
from compliance.config import get_settings
from compliance.jobs import Hook, JobContext
from compliance.llm.client import LLMClient
from compliance.search.tavily import Search
from compliance.store.repo import Store


def make_hooks(
    store: Store, llm: LLMClient | None = None, search: Search | None = None
) -> dict[str, Hook]:
    settings = get_settings()
    hooks: dict[str, Hook] = {}
    if settings.nebius_api_key or llm is not None:
        llm = llm or LLMClient(store)

        def classify_usage(ctx: JobContext) -> str | None:
            return classify_spaces(ctx.model, llm, job_id=ctx.job_id)

        def explain_stage(ctx: JobContext) -> str | None:
            if ctx.report is None:
                return None
            n = reword(ctx.report["questions"], llm, job_id=ctx.job_id)
            ctx.report["explanation"] = explain(ctx.report, llm, job_id=ctx.job_id)
            return "Nemotron wrote the summary" + (f" and reworded {n} question(s)" if n else "")

        hooks["classify_usage"] = classify_usage
        hooks["explain"] = explain_stage

        if settings.tavily_api_key or search is not None:
            search = search or Search(store)

            def freshness(ctx: JobContext) -> str | None:
                if ctx.report is None:
                    return None
                authority = ctx.model["project"]["authority_id"]["value"]
                return apply_to_report(
                    ctx.report, ctx.rulebase.rules, authority, search, llm, store, job_id=ctx.job_id
                )

            hooks["freshness"] = freshness
    return hooks
