"""Tavily client (P3.3, D6, D26): search + extract, limited to an authority's official domains,
cached for 7 days in SQLite, and every call (cached or live) logged to search_usage — the proof of a
"functional, runtime call to the Tavily API" for the Best Use of Tavily prize.

Search results only ever *flag* things (possible amendments, candidate sources). A rule's pass/fail
never depends on what a search returns (D6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from functools import lru_cache
from typing import Any

import yaml
from tavily import TavilyClient

from compliance.config import get_settings
from compliance.store.repo import Store

CACHE_AGE = timedelta(days=7)
MAX_EXTRACT_CHARS = 60_000  # keep extracted pages small enough for prompts and the cache


class SearchError(Exception):
    pass


@lru_cache
def authority_domains(authority_id: str) -> list[str]:
    path = get_settings().rules_dir / "cities" / authority_id / "authority.yaml"
    if not path.exists():
        return []
    return list(yaml.safe_load(path.read_text("utf-8")).get("tavily_domains") or [])


class Search:
    def __init__(
        self, store: Store | None, client_factory: Callable[[], Any] | None = None
    ) -> None:
        self._store = store
        self._factory = client_factory or (
            lambda: TavilyClient(api_key=get_settings().tavily_api_key)
        )
        self._client: Any = None

    def search(
        self,
        query: str,
        *,
        authority_id: str | None = None,
        domains: list[str] | None = None,
        max_results: int = 5,
        depth: str = "basic",
        job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Results as [{url, title, content, score}], newest-first as Tavily ranks them."""
        include = (
            domains
            if domains is not None
            else (authority_domains(authority_id) if authority_id else [])
        )
        request = {
            "query": query,
            "include_domains": include,
            "max_results": max_results,
            "search_depth": depth,
        }
        cached = self._cached("search", request)
        if cached is not None:
            self._log("search", query, True, len(cached["results"]), job_id)
            return cached["results"]
        try:
            resp = self._tavily().search(**request)
        except Exception as e:  # noqa: BLE001 - network / quota / auth all surface the same way
            raise SearchError(f"Tavily search failed: {e}") from e
        results = [
            {
                "url": r.get("url"),
                "title": r.get("title") or "",
                "content": (r.get("content") or "")[:2000],
                "score": r.get("score"),
            }
            for r in resp.get("results", [])
        ]
        self._store_cache("search", request, {"results": results})
        self._log("search", query, False, len(results), job_id)
        return results

    def extract(self, url: str, *, job_id: str | None = None) -> str:
        """Clean text of one page (or PDF), truncated to MAX_EXTRACT_CHARS."""
        request = {"urls": [url]}
        cached = self._cached("extract", request)
        if cached is not None:
            self._log("extract", url, True, 1, job_id)
            return cached["text"]
        try:
            resp = self._tavily().extract(urls=[url])
        except Exception as e:  # noqa: BLE001
            raise SearchError(f"Tavily extract failed: {e}") from e
        results = resp.get("results") or []
        if not results:
            failed = resp.get("failed_results") or []
            raise SearchError(f"Tavily could not extract {url}: {failed[:1]}")
        text = (results[0].get("raw_content") or "")[:MAX_EXTRACT_CHARS]
        self._store_cache("extract", request, {"text": text})
        self._log("extract", url, False, 1, job_id)
        return text

    # ------------------------------------------------------------------ internals

    def _tavily(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    @staticmethod
    def _key(kind: str, request: dict[str, Any]) -> str:
        return (
            f"tavily:{kind}:"
            + hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        )

    def _cached(self, kind: str, request: dict[str, Any]) -> dict[str, Any] | None:
        return self._store.cache_get(self._key(kind, request), CACHE_AGE) if self._store else None

    def _store_cache(self, kind: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        if self._store:
            self._store.cache_put(self._key(kind, request), kind, request, response)

    def _log(self, kind: str, query: str, cached: bool, results: int, job_id: str | None) -> None:
        if self._store:
            self._store.record_search(
                kind=kind, query=query[:300], cached=cached, results=results, job_id=job_id
            )
