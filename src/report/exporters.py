"""Export a report dict (the shape produced by `Report.to_dict()`) to JSON, Markdown, or SARIF."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from src import __version__

_SARIF_SCHEMA_URL = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)
_SEVERITY_TO_SARIF_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
}


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
        # LLM-generated summaries are free text and can contain "|", which
        # would otherwise misalign the table -- escape it like any other
        # Markdown table cell.
        summary = cs["summary"].replace("\n", " ").replace("|", "\\|").strip()
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


def to_sarif(report: Dict[str, Any]) -> str:
    """Serialize `report["issues"]` to a SARIF 2.1.0 log.

    SARIF is what lets DrRepo's findings show up natively in GitHub's code
    scanning UI (Security tab) instead of only in DrRepo's own report. `ruleId`
    is derived from each issue's `source` (e.g. "bandit", "osv.dev",
    "license-audit") since that's the closest thing to a stable "type of
    check" our `Issue` shape carries -- DrRepo doesn't assign per-issue check
    codes the way a linter does.
    """
    rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    for issue in report["issues"]:
        rule_id = issue.get("source") or issue["category"]
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "shortDescription": {"text": rule_id},
                "properties": {"category": issue["category"]},
            }

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": _SEVERITY_TO_SARIF_LEVEL.get(issue["severity"], "warning"),
            "message": {"text": f"{issue['title']} — {issue['description']}"},
        }
        if issue.get("file"):
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": issue["file"]},
                        "region": {"startLine": issue["line"] or 1},
                    }
                }
            ]
        results.append(result)

    sarif_log = {
        "$schema": _SARIF_SCHEMA_URL,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "DrRepo",
                        "informationUri": "https://github.com/ak-rahul/DrRepo",
                        "version": __version__,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif_log, indent=2, ensure_ascii=False)
