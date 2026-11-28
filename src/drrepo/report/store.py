"""Where runs, reports and API jobs are kept: a `ReportStore`.

Two implementations behind one protocol, chosen by `STORE_BACKEND`:

- `JsonFileStore` (`json`, the default): today's `reports/history.json`, scores
  only, 20 runs per repository, for a single host. API jobs live in memory and
  are lost on restart.
- `SQLiteStore` (`sqlite`): one database file with every run's scores *and* full
  report (200 runs per repository), plus the API's jobs, so queued work survives
  a restart and several processes can share it. SQLite serializes writers
  itself (WAL mode, a busy timeout), and every call opens its own connection, so
  one store is safe across threads.

History is a convenience: `attach_history` never lets a failed write fail a
finished analysis. A run record is the same dict in both stores (see
`history.run_record`); `runs()` returns them oldest first.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

from drrepo.config import Config
from drrepo.log import logger
from drrepo.report.history import (
    DEFAULT_HISTORY_PATH,
    compute_deltas,
    load_history,
    record_run,
    repo_key,
    run_record,
)

DEFAULT_SQLITE_PATH = Path("reports") / "drrepo.db"
SQLITE_MAX_RUNS_PER_REPO = 200
_BUSY_TIMEOUT_SECONDS = 15.0
_SCHEMA_VERSION = 1


class ReportStore(Protocol):
    """Score history, full reports (where kept) and API jobs."""

    def runs(self, repo: str | None = None) -> list[dict[str, Any]]:
        """Run records, oldest first: all of them, or one repository's (`repo_key`)."""

    def record(self, report: dict[str, Any]) -> None:
        """Append a finished run. Raises OSError (or sqlite3.Error) if it can't be written."""

    def latest_report(self, repo: str) -> dict[str, Any] | None:
        """The newest full report for a repository, if this store keeps reports."""

    def save_job(self, job: dict[str, Any]) -> None:
        """Insert or replace an API job (`job["id"]` is the key)."""

    def job(self, job_id: str) -> dict[str, Any] | None: ...

    def jobs(
        self, *, statuses: Iterable[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Jobs, newest first, optionally only those in `statuses`."""


class JsonFileStore:
    """Scores in a JSON file (`history.py`), jobs in memory."""

    def __init__(self, path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.path = Path(path)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"JsonFileStore({str(self.path)!r})"

    def runs(self, repo: str | None = None) -> list[dict[str, Any]]:
        history = load_history(self.path)
        return history if repo is None else [r for r in history if r.get("repo_key") == repo]

    def record(self, report: dict[str, Any]) -> None:
        record_run(report, self.path)

    def latest_report(self, repo: str) -> dict[str, Any] | None:
        return None  # the JSON history keeps scores, not reports

    def save_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job["id"]] = dict(job)

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._jobs.get(job_id)
            return dict(found) if found else None

    def jobs(
        self, *, statuses: Iterable[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        wanted = set(statuses) if statuses is not None else None
        with self._lock:
            found = [
                dict(j) for j in self._jobs.values() if wanted is None or j["status"] in wanted
            ]
        return sorted(found, key=lambda j: j["created_at"], reverse=True)[:limit]


_JOB_FIELDS = (
    "id",
    "status",
    "request",
    "client",
    "created_at",
    "started_at",
    "finished_at",
    "progress",
    "error",
    "summary",
    "report",
)
_JSON_JOB_FIELDS = frozenset({"request", "summary", "report"})


class SQLiteStore:
    """Runs, full reports and jobs in one SQLite database."""

    def __init__(
        self, path: Path = DEFAULT_SQLITE_PATH, max_runs_per_repo: int = SQLITE_MAX_RUNS_PER_REPO
    ) -> None:
        self.path = Path(path)
        self.max_runs_per_repo = max_runs_per_repo
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_key TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    commit_sha TEXT,
                    overall_score REAL,
                    record TEXT NOT NULL,
                    report TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_by_repo ON runs (repo_key, id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request TEXT NOT NULL,
                    client TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress TEXT,
                    error TEXT,
                    summary TEXT,
                    report TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (status, created_at);
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    def __repr__(self) -> str:
        return f"SQLiteStore({str(self.path)!r})"

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT_SECONDS)
        db.row_factory = sqlite3.Row
        try:
            with db:  # commits, or rolls back on an exception
                yield db
        finally:
            db.close()

    def runs(self, repo: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if repo is None:
                rows = db.execute("SELECT id, record FROM runs ORDER BY id").fetchall()
            else:
                rows = db.execute(
                    "SELECT id, record FROM runs WHERE repo_key = ? ORDER BY id", (repo,)
                ).fetchall()
        return [{**json.loads(row["record"]), "run_id": row["id"]} for row in rows]

    def record(self, report: dict[str, Any]) -> None:
        entry = run_record(report)
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs (repo_key, timestamp, commit_sha, overall_score, record, report)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry["repo_key"],
                    entry["timestamp"],
                    entry["commit_sha"],
                    entry["overall_score"],
                    json.dumps(entry),
                    json.dumps(report, default=str),
                ),
            )
            db.execute(
                "DELETE FROM runs WHERE repo_key = ? AND id NOT IN ("
                " SELECT id FROM runs WHERE repo_key = ? ORDER BY id DESC LIMIT ?)",
                (entry["repo_key"], entry["repo_key"], self.max_runs_per_repo),
            )

    def latest_report(self, repo: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT report FROM runs WHERE repo_key = ? AND report IS NOT NULL"
                " ORDER BY id DESC LIMIT 1",
                (repo,),
            ).fetchone()
        return json.loads(row["report"]) if row else None

    def save_job(self, job: dict[str, Any]) -> None:
        values = [
            json.dumps(job.get(f), default=str) if f in _JSON_JOB_FIELDS else job.get(f)
            for f in _JOB_FIELDS
        ]
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO jobs (id, status, request, client, created_at, started_at,"
                " finished_at, progress, error, summary, report)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def jobs(
        self, *, statuses: Iterable[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            if statuses is None:
                rows = db.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM jobs WHERE status IN (SELECT value FROM json_each(?))"
                    " ORDER BY created_at DESC LIMIT ?",
                    (json.dumps(list(statuses)), limit),
                ).fetchall()
        return [_job_from_row(row) for row in rows]


def _job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        f: (json.loads(row[f]) if f in _JSON_JOB_FIELDS and row[f] is not None else row[f])
        for f in _JOB_FIELDS
    }


def open_store(config: Config) -> ReportStore:
    """The store `STORE_BACKEND` / `STORE_PATH` name (JSON history by default)."""
    if config.store_backend == "sqlite":
        return SQLiteStore(Path(config.store_path) if config.store_path else DEFAULT_SQLITE_PATH)
    return JsonFileStore(Path(config.store_path) if config.store_path else DEFAULT_HISTORY_PATH)


def attach_history(report: dict[str, Any], store: ReportStore) -> dict[str, Any]:
    """Attach score deltas vs. this repository's previous run (`report["score_history"]`),
    then record this run. Mutates and returns `report`.

    If history can't be read or written (read-only volume, lock timeout, a
    locked database), the finished report is still returned.
    """
    key = repo_key(report["repository"])
    try:
        previous = store.runs(key)
    except (OSError, sqlite3.Error) as e:
        logger.warning(f"Score history not read ({type(e).__name__}: {e})")
        previous = []
    if previous:
        report["score_history"] = compute_deltas(report, previous[-1])
    try:
        store.record(report)
    except (OSError, sqlite3.Error) as e:
        logger.warning(f"Score history not recorded ({type(e).__name__}: {e})")
    return report
