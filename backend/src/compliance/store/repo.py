"""Thin repository over the SQLite store. Plain dicts in, plain dicts out."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from compliance.store.db import Database

PAIR_CODE_TTL = timedelta(minutes=10)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ projects & models

    def create_project(self, name: str) -> str:
        pid = new_id()
        self.db.execute(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)", (pid, name, now())
        )
        return pid

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return dict(row) if row else None

    def touch_project(self, project_id: str) -> None:
        """Note that the project is in use (retention counts from the last use)."""
        self.db.execute("UPDATE projects SET last_opened_at = ? WHERE id = ?", (now(), project_id))

    def idle_projects(self, days: int) -> list[str]:
        """Projects not used for `days` days (never opened counts from creation)."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.db.query(
            "SELECT id FROM projects WHERE COALESCE(last_opened_at, created_at) < ?", (cutoff,)
        )
        return [r["id"] for r in rows]

    def delete_project(self, project_id: str) -> None:
        """The project and everything stored with it in the database (cascades)."""
        self.db.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def model_versions(self, project_id: str) -> list[str]:
        """The project's model versions, newest first."""
        rows = self.db.query(
            "SELECT id FROM model_versions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC",
            (project_id,),
        )
        return [r["id"] for r in rows]

    def delete_model_versions(self, version_ids: list[str]) -> None:
        for vid in version_ids:
            self.db.execute("DELETE FROM model_versions WHERE id = ?", (vid,))

    def rename_project(self, project_id: str, name: str) -> None:
        self.db.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))

    def project_summary(self, project_id: str) -> dict[str, Any] | None:
        """What a project list shows: name, kind, where, whether the site is set, the last check."""
        p = self.get_project(project_id)
        if p is None:
            return None
        brief = {k: v.get("value") for k, v in self.get_brief(project_id).items()}
        latest = self.db.one(
            "SELECT id, source_kind, created_at, model_json FROM model_versions WHERE project_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (project_id,),
        )
        model = json.loads(latest["model_json"]) if latest else None
        report = self.db.one(
            "SELECT id, created_at, report_json FROM reports WHERE project_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (project_id,),
        )
        touched = self.db.one(
            "SELECT MAX(updated_at) AS t FROM briefs WHERE project_id = ?", (project_id,)
        )
        loc = brief.get("project.location") or (
            ((model or {}).get("project") or {}).get("location") or {}
        ).get("value")
        site = (model or {}).get("site") or {}
        edges = site.get("edges") or []
        tags = brief.get("site.edges") or {}
        boundary = bool(brief.get("site.boundary") or site.get("boundary"))
        tagged = bool(edges) and all(
            (tags.get(e["id"]) or {}).get("kind") or (e.get("kind") or {}).get("value")
            for e in edges
        )
        times = [p["created_at"], latest and latest["created_at"], report and report["created_at"]]
        times.append(touched["t"] if touched else None)
        last = None
        if report:
            summary = json.loads(report["report_json"]).get("summary") or {}
            last = {"report_id": report["id"], "at": report["created_at"], **summary}
        return {
            "id": p["id"],
            "name": p["name"],
            "created_at": p["created_at"],
            "updated_at": max(t for t in times if t),
            "source_kind": latest["source_kind"] if latest else None,
            "location": loc,
            "site": {
                "location": bool(loc),
                "plot": boundary,
                "sides": tagged or bool(brief.get("site.boundary") and tags),
            },
            "last_check": last,
        }

    def add_model_version(self, project_id: str, model: dict[str, Any]) -> str:
        vid = new_id()
        self.db.execute(
            "INSERT INTO model_versions (id, project_id, source_kind, created_at, model_json) VALUES (?, ?, ?, ?, ?)",
            (vid, project_id, model["meta"]["source_kind"], now(), json.dumps(model)),
        )
        return vid

    def latest_model(self, project_id: str) -> tuple[str, dict[str, Any]] | None:
        row = self.db.one(
            "SELECT id, model_json FROM model_versions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (project_id,),
        )
        return (row["id"], json.loads(row["model_json"])) if row else None

    def get_model(self, version_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT model_json FROM model_versions WHERE id = ?", (version_id,))
        return json.loads(row["model_json"]) if row else None

    # ------------------------------------------------------------------ brief answers (web)

    def set_brief(self, project_id: str, answers: dict[str, Any]) -> None:
        ts = now()
        with self.db.lock:
            for path, value in answers.items():
                fact = {"value": value, "source": "declared"}
                self.db.execute(
                    "INSERT INTO briefs (project_id, path, value_json, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(project_id, path) DO UPDATE SET value_json = excluded.value_json, "
                    "updated_at = excluded.updated_at",
                    (project_id, path, json.dumps(fact), ts),
                )

    def get_brief(self, project_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.query(
            "SELECT path, value_json FROM briefs WHERE project_id = ?", (project_id,)
        )
        return {r["path"]: json.loads(r["value_json"]) for r in rows}

    # ------------------------------------------------------------------ jobs & reports

    def create_job(self, project_id: str, model_version_id: str) -> str:
        jid, ts = new_id(), now()
        self.db.execute(
            "INSERT INTO jobs (id, project_id, model_version_id, status, stage, pct, created_at, updated_at) "
            "VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?)",
            (jid, project_id, model_version_id, ts, ts),
        )
        return jid

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "pct", "message", "report_id", "error"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self.db.execute(
            f"UPDATE jobs SET {cols}, updated_at = ? WHERE id = ?", (*sets.values(), now(), job_id)
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return dict(row) if row else None

    def save_report(self, report: dict[str, Any]) -> str:
        self.db.execute(
            "INSERT INTO reports (id, project_id, model_version_id, created_at, report_json) VALUES (?, ?, ?, ?, ?)",
            (
                report["id"],
                report["project_id"],
                report["model_version"],
                report["created_at"],
                json.dumps(report),
            ),
        )
        return report["id"]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT report_json FROM reports WHERE id = ?", (report_id,))
        return json.loads(row["report_json"]) if row else None

    # ------------------------------------------------------------------ live packs
    # One per project, from the latest check: a JSON file next to the database (small, read often).

    def _live_path(self, project_id: str):
        from pathlib import Path

        base = Path(self.db.path).parent if self.db.path != ":memory:" else Path(".cache")
        return base / "live" / f"{project_id}.json"

    def save_live_pack(self, project_id: str, pack: dict[str, Any]) -> None:
        path = self._live_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")

    def get_live_pack(self, project_id: str) -> dict[str, Any] | None:
        path = self._live_path(project_id)
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    # ------------------------------------------------------------------ usage

    def record_llm_usage(
        self,
        *,
        role: str,
        model: str,
        ok: bool,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        latency_ms: int | None = None,
        purpose: str | None = None,
        job_id: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO llm_usage (ts, role, model, purpose, job_id, prompt_tokens, completion_tokens, latency_ms, ok) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now(),
                role,
                model,
                purpose,
                job_id,
                prompt_tokens,
                completion_tokens,
                latency_ms,
                int(ok),
            ),
        )

    def record_search(
        self, *, kind: str, query: str, cached: bool, results: int | None, job_id: str | None = None
    ) -> None:
        self.db.execute(
            "INSERT INTO search_usage (ts, kind, query, cached, results, job_id) VALUES (?, ?, ?, ?, ?, ?)",
            (now(), kind, query, int(cached), results, job_id),
        )

    def usage_summary(self) -> dict[str, Any]:
        models = [
            dict(r)
            for r in self.db.query(
                "SELECT role, model, COUNT(*) AS calls, SUM(ok) AS ok_calls, "
                "COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
                "COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
                "CAST(AVG(latency_ms) AS INTEGER) AS avg_latency_ms "
                "FROM llm_usage GROUP BY role, model ORDER BY calls DESC"
            )
        ]
        search = [
            dict(r)
            for r in self.db.query(
                "SELECT kind, COUNT(*) AS calls, SUM(1 - cached) AS live_calls FROM search_usage GROUP BY kind"
            )
        ]
        return {"models": models, "search": search}

    # ------------------------------------------------------------------ tavily cache

    def cache_get(self, key: str, max_age: timedelta) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT response_json, fetched_at FROM tavily_cache WHERE key = ?", (key,)
        )
        if row is None:
            return None
        if datetime.now(UTC) - datetime.fromisoformat(row["fetched_at"]) > max_age:
            return None
        return json.loads(row["response_json"])

    def cache_put(
        self, key: str, kind: str, request: dict[str, Any], response: dict[str, Any]
    ) -> None:
        self.db.execute(
            "INSERT INTO tavily_cache (key, kind, request_json, response_json, fetched_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json, fetched_at = excluded.fetched_at",
            (key, kind, json.dumps(request), json.dumps(response), now()),
        )

    # ------------------------------------------------------------------ pairing

    def create_pair_code(self) -> str:
        """A fresh 6-digit code, valid for 10 minutes and usable once."""
        created = datetime.now(UTC)
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            try:
                self.db.execute(
                    "INSERT INTO pair_codes (code, created_at, expires_at) VALUES (?, ?, ?)",
                    (
                        code,
                        created.isoformat(timespec="seconds"),
                        (created + PAIR_CODE_TTL).isoformat(timespec="seconds"),
                    ),
                )
                return code
            except Exception:  # noqa: BLE001 - code collision with a live code: draw again
                self.db.execute("DELETE FROM pair_codes WHERE expires_at < ?", (now(),))

    def consume_pair_code(self, code: str, device: str | None) -> str | None:
        """Return a new bearer token if the code is valid, else None."""
        with self.db.lock:
            row = self.db.one("SELECT * FROM pair_codes WHERE code = ?", (code,))
            if row is None or row["used_at"] is not None or row["expires_at"] < now():
                return None
            self.db.execute("UPDATE pair_codes SET used_at = ? WHERE code = ?", (now(), code))
            token = secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO tokens (token_hash, device, created_at) VALUES (?, ?, ?)",
                (_hash(token), device, now()),
            )
            return token

    def check_token(self, token: str) -> bool:
        h = _hash(token)
        if self.db.one("SELECT 1 FROM tokens WHERE token_hash = ?", (h,)) is None:
            return False
        self.db.execute("UPDATE tokens SET last_used_at = ? WHERE token_hash = ?", (now(), h))
        return True


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
