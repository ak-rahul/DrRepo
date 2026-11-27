"""Turn category findings into a `Report`, and track scores across runs.

`synthesize_report` is a pure function (no I/O, no LLM). Score history is the
one place a report touches disk other than export: an append-only JSON file
(`reports/history.json`), capped per repository, written atomically.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from drrepo.models import Category, CategoryFinding, InvestigationPlan, Issue, Report, Severity

# ----------------------------------------------------------- synthesis ---

CATEGORY_WEIGHTS = {
    Category.SECURITY: 0.30,
    Category.CODE_QUALITY: 0.25,
    Category.DEPENDENCIES: 0.15,
    Category.MAINTAINABILITY: 0.15,
    Category.DOCUMENTATION: 0.15,
}
MAX_QUICK_WINS = 5


def weighted_overall(findings: dict[str, CategoryFinding]) -> float:
    """Weighted mean over *assessed* categories only. Unassessable categories
    are excluded (and the remaining weights renormalized) rather than counted
    at a made-up neutral score."""
    total = weight_sum = 0.0
    for category, weight in CATEGORY_WEIGHTS.items():
        finding = findings.get(category.value)
        if finding is None or not finding.assessed:
            continue
        total += finding.score * weight
        weight_sum += weight
    return round(total / weight_sum, 1) if weight_sum else 0.0


def quick_wins(issues: list[Issue]) -> list[str]:
    """Distinct recommendations for cheap-to-fix (low/medium) issues, highest impact first."""
    candidates = sorted(
        (i for i in issues if i.severity in (Severity.MEDIUM, Severity.LOW)),
        key=lambda i: (i.severity.rank, -i.occurrences),
    )
    wins: list[str] = []
    for issue in candidates:
        if issue.recommendation and issue.recommendation not in wins:
            wins.append(issue.recommendation)
        if len(wins) >= MAX_QUICK_WINS:
            break
    return wins


def synthesize_report(
    *,
    repository: dict[str, Any],
    category_findings: dict[str, CategoryFinding],
    collector_status: dict[str, dict[str, Any]],
    investigation_plan: InvestigationPlan | None = None,
    generated_at: str = "",
    drrepo_version: str = "",
) -> Report:
    ordered: dict[str, CategoryFinding] = {
        c.value: category_findings[c.value] for c in Category if c.value in category_findings
    }
    all_issues = sorted(
        (issue for finding in ordered.values() for issue in finding.issues),
        key=lambda i: (i.severity.rank, -i.occurrences, i.category.value),
    )
    return Report(
        repository=repository,
        overall_score=weighted_overall(ordered),
        category_scores=ordered,
        issues=all_issues,
        quick_wins=quick_wins(all_issues),
        collector_status=collector_status,
        investigation_plan=investigation_plan.to_dict() if investigation_plan else {},
        generated_at=generated_at,
        drrepo_version=drrepo_version,
    )


def grade(score: float) -> str:
    """Letter grade for display."""
    for threshold, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= threshold:
            return letter
    return "F"


# ------------------------------------------------------------- history ---

DEFAULT_HISTORY_PATH = Path("reports") / "history.json"
_MAX_RUNS_PER_REPO = 20
# The Streamlit app runs analyses on background threads and shares one process across
# sessions, so two runs finishing close together can otherwise race on this
# read-modify-write: both load the same history, append their own entry, and
# the second write silently clobbers the first (lost update). This serializes
# record_run() calls within the process; it doesn't protect against separate
# OS processes writing the same path, which isn't a supported deployment mode
# here (see docs/architecture.md). Writes go through a temp
# file + atomic rename, so a crash mid-write can't truncate the history.
_history_lock = threading.Lock()


def _repo_key(repository: dict[str, Any]) -> str:
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


def previous_run_for(
    repository: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the most recent prior run recorded for this repository, or None."""
    key = _repo_key(repository)
    matches = [r for r in history if r.get("repo_key") == key]
    return matches[-1] if matches else None


def compute_deltas(current_report: dict[str, Any], previous_run: dict[str, Any]) -> dict[str, Any]:
    """Compute score deltas between the current report and a previous run record."""
    category_deltas = {}
    for name, cs in current_report["category_scores"].items():
        prev_score = previous_run.get("category_scores", {}).get(name)
        if prev_score is not None and cs.get("assessed", True):
            category_deltas[name] = round(cs["score"] - prev_score, 1)

    return {
        "previous_timestamp": previous_run["timestamp"],
        "overall_score_delta": round(
            current_report["overall_score"] - previous_run["overall_score"], 1
        ),
        "category_score_deltas": category_deltas,
    }


def record_run(report: dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH) -> None:
    """Append this run's scores to the history file, capped per repository so
    the file doesn't grow unbounded under repeated/CI-style usage."""
    with _history_lock:
        history = load_history(history_path)
        key = _repo_key(report["repository"])

        history.append(
            {
                "repo_key": key,
                "timestamp": datetime.now(UTC).isoformat(),
                "overall_score": report["overall_score"],
                "category_scores": {
                    name: cs["score"]
                    for name, cs in report["category_scores"].items()
                    if cs.get("assessed", True)
                },
            }
        )

        this_repo_runs = [r for r in history if r.get("repo_key") == key]
        if len(this_repo_runs) > _MAX_RUNS_PER_REPO:
            excess = this_repo_runs[: len(this_repo_runs) - _MAX_RUNS_PER_REPO]
            for stale in excess:
                history.remove(stale)

        history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = history_path.with_suffix(history_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        os.replace(tmp_path, history_path)


def attach_and_record_history(
    report: dict[str, Any], history_path: Path = DEFAULT_HISTORY_PATH
) -> dict[str, Any]:
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
