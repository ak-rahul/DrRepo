"""Score history: run records, deltas against the previous run, and the JSON file.

A run record (`run_record`) is the same dict in every store (`report/store.py`).
This module also implements the default store's file: an append-only JSON file
(`reports/history.json`), capped per repository.

Each run also records what its deep investigations really cost (`deep_tokens`),
so the next run can size its budget from measurements instead of a fixed guess
(`deep_investigation_estimate`).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

DEFAULT_HISTORY_PATH = Path("reports") / "history.json"
_MAX_RUNS_PER_REPO = 20
_ESTIMATE_SAMPLES_PER_REPO = 10
_ESTIMATE_SAMPLES_OVERALL = 30
_LOCK_TIMEOUT_SECONDS = 10.0
# record_run() is a read-modify-write, so two runs finishing together would lose
# an update. Two locks prevent that: a thread lock for runs inside one process
# (Streamlit sessions), and a lock file next to the history for separate
# processes (the UI and a CLI run sharing one reports/ directory or docker
# volume). Writes go to a unique temp file and are renamed into
# place atomically, so a crash mid-write can't truncate the history.
_history_lock = threading.Lock()


def repo_key(repository: dict[str, Any]) -> str:
    """The key runs of one repository share: its URL (`report["repository"]["url"]`)."""
    return str(repository.get("url") or repository.get("name", "unknown"))


def load_history(history_path: Path = DEFAULT_HISTORY_PATH) -> list[dict[str, Any]]:
    """Load all recorded runs. Returns `[]` if the file is missing or corrupt --
    a broken history file must never block an analysis from completing."""
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def run_record(report: dict[str, Any]) -> dict[str, Any]:
    """What a store keeps about one finished run, besides the report itself."""
    return {
        "repo_key": repo_key(report["repository"]),
        "timestamp": datetime.now(UTC).isoformat(),
        "commit_sha": report["repository"].get("commit_sha"),
        "overall_score": report["overall_score"],
        "category_scores": {
            name: cs["score"]
            for name, cs in report["category_scores"].items()
            if cs.get("assessed", True)
        },
        "deep_tokens": deep_tokens(report),
    }


def deep_tokens(report: dict[str, Any]) -> list[int]:
    """Tokens each investigation in `report` used, scaled to a full deep one.

    A lite investigation has half the tool calls, so its cost is doubled. Only
    investigations with a recorded budget line count.
    """
    by_label = (report.get("llm_usage") or {}).get("by_label") or {}
    measured = []
    for name, cs in report.get("category_scores", {}).items():
        depth = cs.get("investigation_depth")
        tokens = by_label.get(f"investigation:{name}")
        if depth in ("deep", "lite") and tokens:
            measured.append(int(tokens) * (2 if depth == "lite" else 1))
    return measured


def deep_investigation_estimate(
    repository: dict[str, Any], history: list[dict[str, Any]]
) -> int | None:
    """Mean recorded cost of a deep investigation: this repository's recent runs
    first (cost grows with repository size), else recent runs of any repository.
    None when nothing has been measured yet."""
    key = repo_key(repository)
    own = [t for r in history if r.get("repo_key") == key for t in r.get("deep_tokens", [])]
    sample = (
        own[-_ESTIMATE_SAMPLES_PER_REPO:]
        or [t for r in history for t in r.get("deep_tokens", [])][-_ESTIMATE_SAMPLES_OVERALL:]
    )
    return round(sum(sample) / len(sample)) if sample else None


def compute_deltas(current_report: dict[str, Any], previous_run: dict[str, Any]) -> dict[str, Any]:
    """Compute score deltas between the current report and a previous run record."""
    category_deltas = {}
    for name, cs in current_report["category_scores"].items():
        prev_score = previous_run.get("category_scores", {}).get(name)
        if prev_score is not None and cs.get("assessed", True):
            category_deltas[name] = round(cs["score"] - prev_score, 1)

    return {
        "previous_timestamp": previous_run["timestamp"],
        "previous_commit_sha": previous_run.get("commit_sha"),
        "overall_score_delta": round(
            current_report["overall_score"] - previous_run["overall_score"], 1
        ),
        "category_score_deltas": category_deltas,
    }


def record_run(report: dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    """Append this run's scores to the history file, capped per repository so
    the file doesn't grow unbounded under repeated/CI-style usage.

    Raises OSError (including `filelock.Timeout`) if the history can't be written.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(f"{history_path}.lock", timeout=_LOCK_TIMEOUT_SECONDS)
    with _history_lock, lock:
        history = load_history(history_path)
        entry = run_record(report)
        key = entry["repo_key"]
        history.append(entry)

        this_repo_runs = [r for r in history if r.get("repo_key") == key]
        if len(this_repo_runs) > _MAX_RUNS_PER_REPO:
            excess = this_repo_runs[: len(this_repo_runs) - _MAX_RUNS_PER_REPO]
            for stale in excess:
                history.remove(stale)

        fd, tmp_name = tempfile.mkstemp(
            dir=history_path.parent, prefix=f".{history_path.name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            tmp_path.replace(history_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
