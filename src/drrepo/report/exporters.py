"""Serialize a report dict (`Report.to_dict()` shape) to JSON, Markdown, or SARIF 2.1.0.

All three take the dict form -- never round-trip dict -> dataclass -> dict here.
"""

from __future__ import annotations

import json
from typing import Any

from drrepo.report.synthesis import grade

SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
_SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
_SARIF_SECURITY_SEVERITY = {"critical": "9.5", "high": "7.5", "medium": "5.0", "low": "2.0"}
_SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
FORMATS = ("json", "md", "sarif")


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def _cell(text: str) -> str:
    return (text or "").replace("\n", " ").replace("|", "\\|").strip()


def _location(issue: dict[str, Any]) -> str:
    if not issue.get("file"):
        return ""
    return f"`{issue['file']}:{issue['line']}`" if issue.get("line") else f"`{issue['file']}`"


def to_markdown(report: dict[str, Any]) -> str:
    repo = report.get("repository", {})
    score = float(report.get("overall_score", 0))
    counts = report.get("issue_counts", {})
    lines = [
        f"# DrRepo report: {repo.get('full_name') or repo.get('name', 'Unknown')}",
        "",
        f"**Overall score:** {score:.0f}/100 (grade {grade(score)})  ",
        f"**Repository:** {repo.get('url', '')}  ",
        f"**Generated:** {report.get('generated_at', '')} by DrRepo {report.get('drrepo_version', '')}  ",
        "**Issues:** " + ", ".join(f"{n} {sev}" for sev, n in counts.items()) if counts else "",
        "",
        "## Category scores",
        "",
        "| Category | Score | Depth | Summary |",
        "|---|---|---|---|",
    ]
    for name, cs in report.get("category_scores", {}).items():
        shown = f"{cs['score']:.0f}/100" if cs.get("assessed", True) else "n/a"
        lines.append(
            f"| {name.replace('_', ' ').title()} | {shown} | {cs.get('investigation_depth', 'shallow')} | {_cell(cs.get('summary', ''))} |"
        )

    lines += ["", "## Issues", ""]
    issues = report.get("issues", [])
    if not issues:
        lines.append("No issues found.")
    for issue in issues:
        sev = issue["severity"]
        occurrences = f" ×{issue['occurrences']}" if issue.get("occurrences", 1) > 1 else ""
        lines.append(
            f"### {_SEVERITY_ICON.get(sev, '')} [{sev.upper()}] {issue['title']}{occurrences}"
        )
        lines.append("")
        meta = [f"category: {issue['category']}", f"source: {issue.get('source')}"]
        if issue.get("rule_id"):
            meta.append(f"rule: `{issue['rule_id']}`")
        if issue.get("file"):
            meta.append(f"at {_location(issue)}")
        lines += [
            " · ".join(meta),
            "",
            issue.get("description", ""),
            "",
            f"**Fix:** {issue.get('recommendation', '')}",
            "",
        ]

    if report.get("quick_wins"):
        lines += ["## Quick wins", ""] + [f"- {w}" for w in report["quick_wins"]] + [""]

    deep = {
        n: cs
        for n, cs in report.get("category_scores", {}).items()
        if cs.get("investigation_trace")
    }
    if deep:
        lines += ["## How it investigated", ""]
        for name, cs in deep.items():
            lines.append(
                f"**{name.replace('_', ' ').title()}** ({len(cs['investigation_trace'])} tool calls)"
            )
            lines += [
                f"1. `{t['tool']}({json.dumps(t['tool_input'])[:120]})`"
                for t in cs["investigation_trace"]
            ]
            lines.append("")

    plan = report.get("investigation_plan") or {}
    if plan:
        lines += ["## Investigation plan", ""]
        lines += [f"- **{n}**: {p.get('depth')} — {p.get('rationale')}" for n, p in plan.items()]
        lines.append("")

    lines += ["## Collector status", "", "| Collector | Status | Detail |", "|---|---|---|"]
    for name, status in report.get("collector_status", {}).items():
        lines.append(f"| {name} | {status.get('status')} | {_cell(status.get('detail') or '')} |")
    return "\n".join(lines) + "\n"


def to_sarif(report: dict[str, Any]) -> str:
    """SARIF 2.1.0 for GitHub code scanning. One result per sampled location.

    Rule ids are `<source>/<rule_id>` (e.g. `bandit/B602`, `osv.dev/GHSA-...`),
    so unrelated checks from different tools never collide.
    """
    from drrepo import __version__

    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for issue in report.get("issues", []):
        source = issue.get("source") or issue["category"]
        rule_id = f"{source}/{issue['rule_id']}" if issue.get("rule_id") else source
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": rule_id.replace("/", "_").replace(":", "_"),
                "shortDescription": {"text": issue["title"][:120]},
                "help": {"text": issue.get("recommendation", "")},
                "properties": {
                    "category": issue["category"],
                    "tags": [issue["category"], "security"]
                    if issue["category"] == "security"
                    else [issue["category"]],
                    "security-severity": _SARIF_SECURITY_SEVERITY.get(issue["severity"], "5.0"),
                },
            }
        base = {
            "ruleId": rule_id,
            "level": _SARIF_LEVEL.get(issue["severity"], "warning"),
            "message": {"text": f"{issue['title']}: {issue.get('description', '')}"},
        }
        locations = issue.get("locations") or (
            [{"file": issue["file"], "line": issue.get("line")}] if issue.get("file") else []
        )
        if not locations:
            results.append(base)
        results.extend(
            {
                **base,
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": loc["file"], "uriBaseId": "%SRCROOT%"},
                            "region": {"startLine": max(1, int(loc.get("line") or 1))},
                        }
                    }
                ],
            }
            for loc in locations
        )

    sarif = {
        "$schema": SARIF_SCHEMA_URL,
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
    return json.dumps(sarif, indent=2, ensure_ascii=False)


EXPORTERS = {"json": to_json, "md": to_markdown, "sarif": to_sarif}
