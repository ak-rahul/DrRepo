"""Self-contained HTML report (`--format html`): one file, no server, no scripts.

Opens in any browser, offline, and can be archived or sent as is. Everything
from the analyzed repository is untrusted, so the template is rendered with
Jinja2 autoescaping on, and the only links built from report data are the
repository's GitHub URL and OSV advisory pages, each checked against a strict
pattern first. Collapsible sections use `<details>`, so no JavaScript is needed.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, PackageLoader, select_autoescape

from drrepo.report.synthesis import grade

SEVERITIES = ("critical", "high", "medium", "low")
_GITHUB_URL = re.compile(r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_ADVISORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,80}$")

# Default `Undefined`: optional report fields (description, ref, history) render empty.
_env = Environment(
    loader=PackageLoader("drrepo.report", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _label(name: str) -> str:
    return name.replace("_", " ").title()


def _advisory_url(advisory: str) -> str | None:
    return (
        f"https://osv.dev/vulnerability/{quote(advisory, safe='')}"
        if _ADVISORY_ID.match(advisory)
        else None
    )


def _location(issue: dict[str, Any]) -> str:
    if not issue.get("file"):
        return ""
    return f"{issue['file']}:{issue['line']}" if issue.get("line") else str(issue["file"])


def context(report: dict[str, Any]) -> dict[str, Any]:
    """The template's view of a report: plain values, grouped and ordered."""
    repo = report.get("repository") or {}
    score = float(report.get("overall_score", 0.0))
    issues = report.get("issues") or []
    by_severity = {s: [i for i in issues if i.get("severity") == s] for s in SEVERITIES}
    categories = [
        {
            "name": name,
            "label": _label(name),
            "assessed": cs.get("assessed", True),
            "score": cs.get("score"),
            "depth": cs.get("investigation_depth", "shallow"),
            "summary": cs.get("summary", ""),
            "notes": cs.get("notes") or [],
            "trace": cs.get("investigation_trace") or [],
        }
        for name, cs in (report.get("category_scores") or {}).items()
    ]
    dependencies = sorted(
        report.get("dependencies") or [],
        key=lambda d: (not d.get("vulnerabilities"), d.get("scope") != "runtime", d.get("name")),
    )
    return {
        "repo": repo,
        "repo_url": repo.get("url") if _GITHUB_URL.match(str(repo.get("url") or "")) else None,
        "score": score,
        "grade": grade(score),
        "report": report,
        "counts": report.get("issue_counts") or {},
        "history": report.get("score_history"),
        "categories": categories,
        "severities": SEVERITIES,
        "by_severity": by_severity,
        "quick_wins": report.get("quick_wins") or [],
        "dependencies": dependencies,
        "vulnerable": sum(1 for d in dependencies if d.get("vulnerabilities")),
        "suppressed": report.get("suppressed") or [],
        "plan": report.get("investigation_plan") or {},
        "collectors": report.get("collector_status") or {},
        "usage": report.get("llm_usage"),
        "provenance": report.get("provenance") or {},
        "label": _label,
        "location": _location,
        "advisory_url": _advisory_url,
    }


def to_html(report: dict[str, Any]) -> str:
    return _env.get_template("report.html").render(**context(report))
