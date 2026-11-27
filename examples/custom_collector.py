"""Extend the pipeline: add a recon collector and an analyst that scores it.

This adds a `todo_markers` collector (counts TODO/FIXME/XXX/HACK comments in
source files) and swaps in a maintainability analyst that turns a high marker
density into an issue. Everything else (graph wiring, fan-in, planner, deep
investigations, report, exporters) picks the new collector up automatically.

    uv run python examples/custom_collector.py https://github.com/psf/requests

The same steps add a collector to DrRepo itself; see docs/development.md.
"""

from __future__ import annotations

import argparse
import re

from drrepo.agents.analysts import default_analysts
from drrepo.agents.analysts.base import (
    Assessment,
    Recon,
    collector_data,
    decay_score,
    issue_penalty,
    sort_issues,
)
from drrepo.agents.analysts.maintainability import MaintainabilityAnalyst
from drrepo.config import Config
from drrepo.log import configure_logging
from drrepo.models import Category, CollectorResult, CollectorStatus, Issue, Location, Severity
from drrepo.pipeline import COLLECTORS, CollectorSpec, RunContext, State, Workflow
from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix
from drrepo.service import AnalysisService

MARKER = re.compile(r"(?:#|//|/\*)\s*(TODO|FIXME|XXX|HACK)\b")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".c", ".cpp"}
MARKERS_PER_KLOC_LIMIT = 5.0


# ---- 1. the collector: plain code, returns a CollectorResult, never raises --


def collect_todo_markers(clone_path: str) -> CollectorResult:
    """data: {"total": int, "lines_scanned": int, "by_marker": {str: int},
    "samples": [{"file": str, "line": int, "marker": str}]}"""
    by_marker: dict[str, int] = {}
    samples: list[dict[str, object]] = []
    lines_scanned = 0
    for path in iter_repo_files(clone_path):
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        text = read_text_file(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            lines_scanned += 1
            match = MARKER.search(line)
            if match:
                marker = match.group(1)
                by_marker[marker] = by_marker.get(marker, 0) + 1
                if len(samples) < 20:
                    samples.append(
                        {"file": relative_posix(path, clone_path), "line": number, "marker": marker}
                    )
    return CollectorResult(
        name="todo_markers",
        status=CollectorStatus.OK,
        data={
            "total": sum(by_marker.values()),
            "lines_scanned": lines_scanned,
            "by_marker": by_marker,
            "samples": samples,
        },
    )


def _run_todo_markers(state: State, ctx: RunContext) -> CollectorResult:
    return collect_todo_markers(state["clone_path"] or "")


TODO_SPEC = CollectorSpec(
    "todo_markers", _run_todo_markers, "Counting TODO/FIXME markers", needs_clone=True
)


# ---- 2. the analyst: deterministic issue + score from the collector output --


class TodoAwareMaintainabilityAnalyst(MaintainabilityAnalyst):
    def assess(self, recon: Recon) -> Assessment:
        assessment = super().assess(recon)
        data = collector_data(recon, "todo_markers")
        if not assessment.assessed or not data or not data["lines_scanned"]:
            return assessment

        per_kloc = data["total"] / data["lines_scanned"] * 1000
        if per_kloc <= MARKERS_PER_KLOC_LIMIT:
            return assessment

        issue = Issue(
            severity=Severity.LOW,
            category=Category.MAINTAINABILITY,
            title=f"High TODO/FIXME density ({per_kloc:.1f} per 1k lines)",
            description=f"{data['total']} unresolved markers: {data['by_marker']}.",
            recommendation="Triage the markers into tracked issues and delete the stale ones.",
            source="todo_markers",  # distinct source, so SARIF rule ids don't collide
            rule_id="density",
            locations=[Location(s["file"], s["line"]) for s in data["samples"]],
            occurrences=data["total"],
        )
        assessment.issues = sort_issues([*assessment.issues, issue])
        assessment.score = decay_score(
            issue_penalty([issue]), self.rescore_scale, base=assessment.score
        )
        return assessment


# ---- 3. wire both in: the graph is rebuilt from the collector specs ---------


def build_service(config: Config) -> AnalysisService:
    analysts = default_analysts()
    analysts[Category.MAINTAINABILITY] = TodoAwareMaintainabilityAnalyst()
    workflow = Workflow(analysts=analysts, collectors=(*COLLECTORS, TODO_SPEC))
    return AnalysisService(config, workflow=workflow)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DrRepo with a custom collector.")
    parser.add_argument("repo_url", nargs="?", default="https://github.com/psf/requests")
    args = parser.parse_args()

    config = Config.from_env()
    configure_logging(config.log_level, console_level="WARNING")
    report = build_service(config).analyze(args.repo_url, deep=False, record_history=False)

    print(f"todo_markers collector: {report['collector_status']['todo_markers']}")
    maintainability = report["category_scores"]["maintainability"]
    print(f"maintainability score: {maintainability['score']}")
    for issue in maintainability["issues"]:
        print(f"  [{issue['severity']}] {issue['title']}")
    if not any(i["source"] == "todo_markers" for i in maintainability["issues"]):
        print(f"  (marker density is within {MARKERS_PER_KLOC_LIMIT} per 1k lines: no issue)")


if __name__ == "__main__":
    main()
