"""Export a report dict (the shape produced by `Report.to_dict()`) to JSON or Markdown."""

from __future__ import annotations

import json
from typing import Any, Dict


def to_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def to_markdown(report: Dict[str, Any]) -> str:
    repo = report["repository"]

    lines = [
        f"# DrRepo Report: {repo.get('name', 'Unknown')}",
        "",
        f"**URL:** {repo.get('url', '')}  ",
        f"**Overall Score:** {report['overall_score']}/100",
        "",
        "## Category Scores",
        "",
        "| Category | Score | Summary |",
        "|---|---|---|",
    ]
    for name, cs in report["category_scores"].items():
        summary = cs["summary"].replace("\n", " ").strip()
        lines.append(f"| {name.replace('_', ' ').title()} | {cs['score']}/100 | {summary} |")

    lines += ["", "## Issues", ""]
    if not report["issues"]:
        lines.append("No issues found.")
    for issue in report["issues"]:
        location = f" ({issue['file']}:{issue['line']})" if issue.get("file") else ""
        lines.append(
            f"- **[{issue['severity'].upper()}]** {issue['title']}{location} — {issue['recommendation']}"
        )

    lines += ["", "## Quick Wins", ""]
    for win in report["quick_wins"]:
        lines.append(f"- {win}")

    lines += ["", "## Collector Status", ""]
    for name, status in report["collector_status"].items():
        lines.append(f"- **{name}**: {status}")

    return "\n".join(lines)
