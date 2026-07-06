"""Local score-history tracking across repeated analyses of the same repository.

Append-only JSON store (`reports/history.json` by default), keyed by
repository URL. Deliberately kept outside `synthesizer.py`: the synthesizer
stays a pure, I/O-free function of in-memory data (easy to unit test), while
this module owns the one place a report touches disk for anything other than
being exported. Not part of the `Report`/`CategoryScore` dataclasses either,
for the same reason -- it's a cross-run concern, not a single run's output.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_HISTORY_PATH = Path("reports") / "history.json"
_MAX_RUNS_PER_REPO = 20
# app.py runs analyses on background threads and shares one process across
# sessions, so two runs finishing close together can otherwise race on this
# read-modify-write: both load the same history, append their own entry, and
# the second write silently clobbers the first (lost update). This serializes
# record_run() calls within the process; it doesn't protect against separate
# OS processes writing the same path, which isn't a supported deployment mode
# here (see CLI vs. Streamlit split in CLAUDE.md).
_history_lock = threading.Lock()


def _repo_key(repository: Dict[str, Any]) -> str:
    return str(repository.get("url") or repository.get("name", "unknown"))


def load_history(history_path: Path = DEFAULT_HISTORY_PATH) -> List[Dict[str, Any]]:
    """Load all recorded runs. Returns `[]` if the file is missing or corrupt --
    a broken history file must never block an analysis from completing."""
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def previous_run_for(
    repository: Dict[str, Any], history: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Return the most recent prior run recorded for this repository, or None."""
    key = _repo_key(repository)
    matches = [r for r in history if r.get("repo_key") == key]
    return matches[-1] if matches else None


def compute_deltas(current_report: Dict[str, Any], previous_run: Dict[str, Any]) -> Dict[str, Any]:
    """Compute score deltas between the current report and a previous run record."""
    category_deltas = {}
    for name, cs in current_report["category_scores"].items():
        prev_score = previous_run.get("category_scores", {}).get(name)
        if prev_score is not None:
            category_deltas[name] = round(cs["score"] - prev_score, 1)

    return {
        "previous_timestamp": previous_run["timestamp"],
        "overall_score_delta": round(
            current_report["overall_score"] - previous_run["overall_score"], 1
        ),
        "category_score_deltas": category_deltas,
    }


def record_run(report: Dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    """Append this run's scores to the history file, capped per repository so
    the file doesn't grow unbounded under repeated/CI-style usage."""
    with _history_lock:
        history = load_history(history_path)
        key = _repo_key(report["repository"])

        history.append(
            {
                "repo_key": key,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "overall_score": report["overall_score"],
                "category_scores": {
                    name: cs["score"] for name, cs in report["category_scores"].items()
                },
            }
        )

        this_repo_runs = [r for r in history if r.get("repo_key") == key]
        if len(this_repo_runs) > _MAX_RUNS_PER_REPO:
            excess = this_repo_runs[: len(this_repo_runs) - _MAX_RUNS_PER_REPO]
            for stale in excess:
                history.remove(stale)

        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def attach_and_record_history(
    report: Dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH
) -> Dict[str, Any]:
    """Compute score deltas vs. the previous run for this repo (if any), attach
    them under `report["score_history"]`, then append this run to the history
    file. Mutates and returns `report`. Call once per completed run, before
    the report is displayed or exported.
    """
    history = load_history(history_path)
    previous = previous_run_for(report["repository"], history)
    if previous is not None:
        report["score_history"] = compute_deltas(report, previous)

    record_run(report, history_path)
    return report
