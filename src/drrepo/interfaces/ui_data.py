"""Pure view helpers for the Streamlit UI: escaping, filtering, and table rows.

Kept free of Streamlit so they are unit-tested directly. Everything a report
contains that came from the analyzed repository (titles, descriptions, file
names, agent output) is untrusted: `escape_markdown` makes it inert before it
reaches any widget that renders Markdown (markdown, caption, expander and
metric labels), so a planted `![](https://...)` can't load a remote image and
`$...$` can't render as LaTeX. Tables (`st.dataframe`) show plain text and need
no escaping.
"""

from __future__ import annotations

import json
import re
from typing import Any

SEVERITIES = ("critical", "high", "medium", "low")
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
DEPTH_ICON = {"deep": "🕵️", "lite": "🔎", "shallow": ""}
AGENT_PREFIX = "investigator:"
ORIGINS = ("All", "Scanners and checks", "Agents")
MARKS = ("[unverified]", "[disputed]")

# Characters that open a link, image, emphasis, code span, HTML tag, heading,
# table, strikethrough or math block (Streamlit renders `$...$` as LaTeX) anywhere
# in a line. Escaped with a backslash (valid CommonMark), they render literally.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~$])")
# Markers that only matter at the start of a line: bullets, rules, setext
# underlines, block quotes (`>` is escaped above) and ordered lists ("1.").
_LINE_START = re.compile(r"^(\s*)([-=])", re.MULTILINE)
_ORDERED = re.compile(r"^(\s*\d{1,9})([.)])", re.MULTILINE)


def escape_markdown(text: Any) -> str:
    """`text` rendered literally by any Streamlit Markdown widget."""
    escaped = _MARKDOWN_SPECIAL.sub(r"\\\1", str(text or ""))
    escaped = _LINE_START.sub(r"\1\\\2", escaped)
    return _ORDERED.sub(r"\1\\\2", escaped)


def label(name: str) -> str:
    """`code_quality` -> `Code Quality`."""
    return name.replace("_", " ").title()


def location(issue: dict[str, Any]) -> str:
    if not issue.get("file"):
        return ""
    return f"{issue['file']}:{issue['line']}" if issue.get("line") else str(issue["file"])


def issue_heading(issue: dict[str, Any]) -> str:
    """An escaped one-line heading: icon, title, occurrence count, location."""
    times = issue.get("occurrences", 1)
    count = f" ×{times}" if times > 1 and "occurrence" not in issue["title"] else ""
    where = location(issue)
    return (
        f"{SEVERITY_ICON.get(issue['severity'], '⚪')} {escape_markdown(issue['title'])}{count}"
        + (f" — {escape_markdown(where)}" if where else "")
    )


def filter_issues(
    issues: list[dict[str, Any]],
    *,
    severities: list[str] | None = None,
    categories: list[str] | None = None,
    sources: list[str] | None = None,
    origin: str = "All",
    query: str = "",
    hide_marked: bool = False,
) -> list[dict[str, Any]]:
    """Issues matching every given filter. `query` matches title, file, source or rule,
    case-insensitively; `hide_marked` drops [unverified]/[disputed] agent findings."""
    needle = query.strip().lower()
    out = []
    for issue in issues:
        if severities is not None and issue["severity"] not in severities:
            continue
        if categories is not None and issue["category"] not in categories:
            continue
        if sources is not None and issue.get("source") not in sources:
            continue
        is_agent = str(issue.get("source", "")).startswith(AGENT_PREFIX)
        if origin == "Agents" and not is_agent:
            continue
        if origin == "Scanners and checks" and is_agent:
            continue
        if hide_marked and issue["title"].startswith(MARKS):
            continue
        if needle:
            haystack = " ".join(
                str(issue.get(k) or "") for k in ("title", "file", "source", "rule_id")
            ).lower()
            if needle not in haystack:
                continue
        out.append(issue)
    return out


def page(items: list[Any], number: int, size: int) -> tuple[list[Any], int]:
    """Items on 1-based page `number`, and the page count (at least 1)."""
    pages = max(1, -(-len(items) // size))
    number = min(max(1, number), pages)
    return items[(number - 1) * size : number * size], pages


def dependency_rows(report: dict[str, Any], vulnerable_only: bool = False) -> list[dict[str, Any]]:
    rows = [
        {
            "ecosystem": d["ecosystem"],
            "package": d["name"],
            "version": d["version"],
            "scope": d["scope"],
            "license": d.get("license") or "",
            "advisories": len(d.get("vulnerabilities", [])),
            "advisory ids": ", ".join(d.get("vulnerabilities", [])[:5]),
        }
        for d in report.get("dependencies", [])
    ]
    if vulnerable_only:
        rows = [r for r in rows if r["advisories"]]
    return sorted(rows, key=lambda r: (-r["advisories"], r["ecosystem"], r["package"]))


def license_counts(report: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in report.get("dependencies", []):
        if d.get("scope") == "runtime":
            key = d.get("license") or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def usage_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    usage = report.get("llm_usage") or {}
    by_label = usage.get("by_label") or {}
    total = sum(by_label.values()) or 1
    return [
        {"step": step, "tokens": tokens, "share": f"{tokens / total:.0%}"}
        for step, tokens in sorted(by_label.items(), key=lambda kv: -kv[1])
    ]


def suppressed_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "severity": e["issue"]["severity"],
            "issue": e["issue"]["title"],
            "location": location(e["issue"]),
            "rule": e["suppression"]["rule"],
            "reason": e["suppression"]["reason"],
            "origin": e["suppression"]["origin"],
            "expires": e["suppression"].get("expires") or "",
        }
        for e in report.get("suppressed", [])
    ]


def provenance_rows(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Tables for the details tab: model per role, tool versions, instruction hashes."""
    provenance = report.get("provenance") or {}
    llm = provenance.get("llm") or {}
    return {
        "models": [
            {"role": role, "provider": llm.get("provider", ""), "model": model}
            for role, model in (llm.get("roles") or {}).items()
        ],
        "tools": [
            {"tool": tool, "version": version or "not installed"}
            for tool, version in sorted((provenance.get("tools") or {}).items())
        ],
        "instructions": [
            {"instructions": name, "hash": digest}
            for name, digest in sorted((provenance.get("instructions") or {}).items())
        ],
    }


def history_points(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chart rows (one per recorded run) from score-history records, oldest first."""
    return [
        {"run": r["timestamp"][:16].replace("T", " "), "overall": r["overall_score"]}
        for r in runs
        if r.get("timestamp") and r.get("overall_score") is not None
    ]


def category_delta_rows(diff: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"category": label(name), "base": c["base"], "head": c["head"], "change": c["delta"]}
        for name, c in diff.get("category_deltas", {}).items()
    ]


def is_agent_finding(issue: dict[str, Any]) -> bool:
    return str(issue.get("source", "")).startswith("investigator:")


def evidence_steps(issue: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool calls of the issue's investigation that touched the cited file, in order:
    what the agent actually read before it reported the finding."""
    if not is_agent_finding(issue) or not issue.get("file"):
        return []
    trace = (report.get("category_scores", {}).get(issue["category"]) or {}).get(
        "investigation_trace", []
    )
    cited = str(issue["file"])
    return [
        step
        for step in trace
        if cited in json.dumps(step.get("tool_input", {}))
        or cited in str(step.get("observation", ""))
    ]
