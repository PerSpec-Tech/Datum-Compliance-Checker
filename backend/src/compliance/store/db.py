"""SQLite store: one file, standard-library sqlite3, idempotent schema.

A single connection guarded by a lock is plenty for the hackathon load (one demo server, a handful
of judges). Everything JSON-shaped is stored as text.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from compliance.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_opened_at  TEXT                    -- any use of the project; drives retention
);
CREATE TABLE IF NOT EXISTS model_versions (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    model_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS model_versions_project ON model_versions(project_id, created_at);
-- Answers given in the web app (PATCH /brief): path → Fact JSON, always source "declared".
CREATE TABLE IF NOT EXISTS briefs (
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (project_id, path)
);
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL,
    status           TEXT NOT NULL,          -- queued | running | done | error
    stage            TEXT,
    pct              REAL,
    message          TEXT,
    report_id        TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    report_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_project ON reports(project_id, created_at);
-- Every Token Factory call (proof of Nebius/NVIDIA use for judges).
CREATE TABLE IF NOT EXISTS llm_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    role              TEXT NOT NULL,
    model             TEXT NOT NULL,
    purpose           TEXT,
    job_id            TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER,
    ok                INTEGER NOT NULL
);
-- Every Tavily call, cached or not (proof of runtime Tavily use).
CREATE TABLE IF NOT EXISTS search_usage (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL,                 -- search | extract
    query     TEXT NOT NULL,
    cached    INTEGER NOT NULL,
    results   INTEGER,
    job_id    TEXT
);
CREATE TABLE IF NOT EXISTS tavily_cache (
    key           TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    request_json  TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pair_codes (
    code       TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash   TEXT PRIMARY KEY,               -- sha256 of the token; the token itself is never stored
    device       TEXT,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
"""


class Database:
    """One SQLite connection shared across threads, serialised by a lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def migrate(self) -> None:
        """Create anything missing. Safe to run on every start."""
        with self.lock:
            self._conn.executescript(SCHEMA)
            # Columns added after the first release: SQLite has no ADD COLUMN IF NOT EXISTS.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(projects)")}
            if "last_opened_at" not in cols:
                self._conn.execute("ALTER TABLE projects ADD COLUMN last_opened_at TEXT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self.lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self.lock:
            self._conn.close()


_default: Database | None = None
_default_lock = threading.Lock()


def get_db() -> Database:
    """The app-wide database at APP_DB_PATH (created on first use)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Database(get_settings().app_db_path)
        return _default
