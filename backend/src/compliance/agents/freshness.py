"""Freshness checker: has a regulation behind a fail/advisory been amended since our
source? Tavily searches the authority's official domains at runtime; Nemotron Nano triages the hits.

Only the `freshness` flag changes — never a rule's logic or a result's status. Each verdict is
cached for 7 days per rule, so repeat checks don't spend search credits.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from compliance.llm.client import LLMClient
from compliance.llm.prompts import render
from compliance.search.tavily import Search
from compliance.store.repo import Store

MAX_RULES_PER_JOB = 6  # keeps each check to a handful of searches
VERDICT_AGE = timedelta(days=7)
SOURCE_DATES = {"udcpr2020": "2025-01-30", "nbc2016": "2016", "mfa2006": "2025-07-07"}
# Deterministic pre-filter (the model only sees plausible amendment notices).
_AMENDING = re.compile(r"amend|modif|corrigend|addend|notification|substitut|draft|sanction", re.I)
_CONSOLIDATED = re.compile(r"(updated|consolidated|final)?[\s_%20-]*(u?dcpr)", re.I)
_YEAR = re.compile(r"\b(20[0-4]\d)\b")


def candidates(results: list[dict[str, Any]], source_date: str) -> list[dict[str, Any]]:
    """Results that could be an amendment newer than our source; drops consolidated copies and
    anything dated before the source (e.g. an older "Updated-UDCPR-2022.pdf")."""
    source_year = int(source_date[:4]) if source_date[:4].isdigit() else None
    keep = []
    for r in results:
        head = f"{r['title']} {r['url']}"
        if not _AMENDING.search(f"{head} {r['content'][:400]}"):
            continue
        if _CONSOLIDATED.search(r["url"]) and not _AMENDING.search(head):
            continue  # a full copy of the regulations, not a change to them
        years = [int(y) for y in _YEAR.findall(head)]
        if source_year and years and max(years) < source_year:
            continue  # older than the version our rule was written from
        keep.append(r)
    return keep


SCHEMA = {
    "name": "freshness",
    "schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["current", "possibly_superseded"]},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "reason": {"type": "string"},
        },
        "required": ["status", "url", "reason"],
        "additionalProperties": False,
    },
}


def check_rule(
    rule_doc: dict[str, Any],
    authority_id: str | None,
    search: Search,
    llm: LLMClient,
    store: Store | None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Returns a Freshness dict {status, url, checked} (+ 'reason', not part of the contract)."""
    key = f"freshness:{rule_doc['id']}"
    if store and (hit := store.cache_get(key, VERDICT_AGE)) is not None:
        return hit

    clause = rule_doc["clause"]
    doc_id = clause["source"].split()[0]
    query = f"{clause['ref']} {rule_doc['title']} UDCPR amendment modification notification"
    found = search.search(query, authority_id=authority_id, max_results=5, job_id=job_id)
    source_date = SOURCE_DATES.get(doc_id, "unknown")
    results = candidates(found, source_date)
    today = datetime.now(UTC).date().isoformat()
    if not results:
        verdict = {
            "status": "current",
            "url": None,
            "checked": today,
            "reason": f"no amendment notices among {len(found)} official results",
        }
    else:
        rule = {
            "regulation": clause["ref"],
            "title": rule_doc["title"],
            "excerpt": clause["excerpt"],
            "source": clause["source"],
            "source_date": source_date,
        }
        hits = [
            {"title": r["title"], "url": r["url"], "snippet": r["content"][:600]} for r in results
        ]
        _, prompt = render(
            "freshness",
            rule_json=json.dumps(rule, ensure_ascii=False),
            results_json=json.dumps(hits, ensure_ascii=False),
        )
        out = llm.chat(
            "fast",
            [{"role": "user", "content": prompt}],
            schema=SCHEMA,
            reasoning=False,
            purpose="freshness",
            job_id=job_id,
        ).data
        urls = {r["url"] for r in results}
        url = out["url"] if out["url"] in urls else None  # only URLs we actually found
        status = out["status"] if (out["status"] == "current" or url) else "current"
        verdict = {"status": status, "url": url, "checked": today, "reason": out["reason"][:300]}
    if store:
        store.cache_put(key, "freshness", {"rule": rule_doc["id"]}, verdict)
    return verdict


def apply_to_report(
    report: dict[str, Any],
    rules: dict[str, Any],
    authority_id: str | None,
    search: Search,
    llm: LLMClient,
    store: Store | None,
    *,
    job_id: str | None = None,
) -> str:
    """Check the rules behind fails/advisories (most severe first) and stamp each result."""
    order = {"critical": 0, "major": 1, "minor": 2}
    flagged = [r for r in report["results"] if r["status"] in ("fail", "advisory")]
    rule_ids: list[str] = []
    for r in sorted(flagged, key=lambda r: order[r["severity"]]):
        if r["rule_id"] not in rule_ids:
            rule_ids.append(r["rule_id"])
    rule_ids = rule_ids[:MAX_RULES_PER_JOB]
    # Independent lookups: run them side by side (Tavily + Nano are network-bound).
    with ThreadPoolExecutor(max_workers=MAX_RULES_PER_JOB) as pool:
        futures = {
            rid: pool.submit(
                check_rule, rules[rid].doc, authority_id, search, llm, store, job_id=job_id
            )
            for rid in rule_ids
        }
        verdicts = {rid: f.result() for rid, f in futures.items()}
    for r in report["results"]:
        v = verdicts.get(r["rule_id"])
        if v:
            r["freshness"] = {"status": v["status"], "url": v["url"], "checked": v["checked"]}
    superseded = [rid for rid, v in verdicts.items() if v["status"] == "possibly_superseded"]
    plural = "s" if len(verdicts) != 1 else ""
    msg = f"Tavily checked {len(verdicts)} regulation{plural} for amendments"
    return msg + (f"; {len(superseded)} may have changed" if superseded else "; none found")
