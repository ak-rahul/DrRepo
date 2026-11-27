"""Serialize a report dict (`Report.to_dict()` shape) to JSON, Markdown, SARIF 2.1.0,
a CycloneDX 1.6 SBOM, or a compact Markdown summary (PR comments, CI step summaries).

Every exporter takes the dict form -- never round-trip dict -> dataclass -> dict here.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import quote

from drrepo.models import rule_key
from drrepo.report.synthesis import grade

SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
_SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
_SARIF_SECURITY_SEVERITY = {"critical": "9.5", "high": "7.5", "medium": "5.0", "low": "2.0"}
_SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
FORMATS = ("json", "md", "sarif", "cdx", "summary")


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def _cell(text: str) -> str:
    return (text or "").replace("\n", " ").replace("|", "\\|").strip()


def _location(issue: dict[str, Any]) -> str:
    if not issue.get("file"):
        return ""
    return f"`{issue['file']}:{issue['line']}`" if issue.get("line") else f"`{issue['file']}`"


def _count(issue: dict[str, Any]) -> str:
    """` ×N` for an aggregated issue, unless its title already states the count."""
    n = issue.get("occurrences", 1)
    return f" ×{n}" if n > 1 and "occurrence" not in issue["title"] else ""


def to_markdown(report: dict[str, Any]) -> str:
    repo = report.get("repository", {})
    score = float(report.get("overall_score", 0))
    counts = report.get("issue_counts", {})
    lines = [
        f"# DrRepo report: {repo.get('full_name') or repo.get('name', 'Unknown')}",
        "",
        f"**Overall score:** {score:.0f}/100 (grade {grade(score)})  ",
        f"**Repository:** {repo.get('url', '')}  ",
        *(
            [
                f"**Commit:** `{repo['commit_sha'][:12]}`"
                + (f" ({repo['ref']})" if repo.get("ref") else "")
                + "  "
            ]
            if repo.get("commit_sha")
            else []
        ),
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
        lines.append(
            f"### {_SEVERITY_ICON.get(sev, '')} [{sev.upper()}] {issue['title']}{_count(issue)}"
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
    suppressed = report.get("suppressed", [])
    if suppressed:
        lines += [
            "",
            f"## Suppressed ({len(suppressed)})",
            "",
            "Excluded from scores and quick wins by a suppression file.",
            "",
            "| Issue | Location | Reason | Origin | Expires |",
            "|---|---|---|---|---|",
        ]
        for entry in suppressed:
            issue, s = entry["issue"], entry["suppression"]
            lines.append(
                f"| {_cell(issue['title'])} | {_location(issue) or '-'} | {_cell(s['reason'])} "
                f"| {s['origin']} | {s.get('expires') or '-'} |"
            )
    return "\n".join(lines) + "\n"


# Text in a summary comes from the analyzed repository (scanner messages, file names,
# agent output). Where it is posted as a PR comment, it must not ping people or load
# remote content: mentions get a zero-width space, and HTML and images are inert.
_MENTION = re.compile(r"(?<![A-Za-z0-9_.`-])@(?=[A-Za-z0-9])")


def _inert(text: str) -> str:
    text = _cell(text).replace("<", "&lt;").replace(">", "&gt;").replace("![", "!\\[")
    return _MENTION.sub("@\u200b", text)


def to_summary(report: dict[str, Any], max_issues: int = 10) -> str:
    """Score, category table and the most severe issues: short enough for a PR comment."""
    repo = report.get("repository", {})
    score = float(report.get("overall_score", 0))
    counts = report.get("issue_counts", {})
    name = _inert(repo.get("full_name") or repo.get("name", "repository"))
    lines = [f"### DrRepo: {name}: {score:.0f}/100 (grade {grade(score)})", ""]
    facts = []
    if repo.get("commit_sha"):
        facts.append(f"commit `{repo['commit_sha'][:12]}`")
    if counts:
        facts.append(", ".join(f"{n} {sev}" for sev, n in counts.items()))
    delta = (report.get("score_history") or {}).get("overall_score_delta")
    if delta:
        facts.append(f"{delta:+.1f} since the previous run")
    if facts:
        lines += [" · ".join(facts), ""]

    lines += ["| Category | Score |", "|---|---|"]
    for key, cs in report.get("category_scores", {}).items():
        shown = f"{cs['score']:.0f}" if cs.get("assessed", True) else "n/a"
        lines.append(f"| {key.replace('_', ' ').title()} | {shown} |")

    issues = report.get("issues", [])
    if issues:
        lines += ["", "| Severity | Issue | Location |", "|---|---|---|"]
        for issue in issues[:max_issues]:
            sev = issue["severity"]
            lines.append(
                f"| {_SEVERITY_ICON.get(sev, '')} {sev} | {_inert(issue['title'])}{_count(issue)} "
                f"| {_inert(_location(issue)) or '-'} |"
            )
        if len(issues) > max_issues:
            lines += ["", f"…and {len(issues) - max_issues} more in the full report."]
    else:
        lines += ["", "No issues found."]
    suppressed = len(report.get("suppressed", []))
    if suppressed:
        lines += ["", f"{suppressed} suppressed finding(s) excluded from the score."]
    lines += ["", f"<sub>DrRepo {_inert(report.get('drrepo_version', ''))}</sub>"]
    return "\n".join(lines) + "\n"


def diff_to_markdown(diff: dict[str, Any], max_issues: int = 10) -> str:
    """What a change made better or worse (`report.diff`), short enough for a PR comment.
    Repository text is neutralized as in `to_summary`."""
    name = _inert(diff["repository"].get("full_name") or diff["repository"].get("name") or "")
    base, head = diff["base"], diff["head"]

    def side(s: dict[str, Any]) -> str:
        sha = f"`{s['commit_sha'][:12]}`" if s.get("commit_sha") else "?"
        score = f"{s['overall_score']:.0f}" if s.get("overall_score") is not None else "n/a"
        return f"{sha} ({score})"

    delta = diff.get("overall_delta")
    verdict = "no change" if not delta else f"{delta:+.1f}"
    lines = [
        f"### DrRepo diff: {name}: {verdict}",
        "",
        f"{side(base)} → {side(head)} · {len(diff['new_issues'])} new, "
        f"{len(diff['worsened_issues'])} worse, {len(diff['fixed_issues'])} fixed, "
        f"{diff['unchanged_issues']} unchanged",
        "",
        "| Category | Base | Head | Change |",
        "|---|---|---|---|",
    ]
    for key, c in diff["category_deltas"].items():
        shown = [f"{c[k]:.0f}" if c[k] is not None else "n/a" for k in ("base", "head")]
        change = f"{c['delta']:+.1f}" if c["delta"] else "-"
        lines.append(f"| {key.replace('_', ' ').title()} | {shown[0]} | {shown[1]} | {change} |")

    def table(title: str, issues: list[dict[str, Any]], note: list[str] | None = None) -> None:
        if not issues:
            return
        lines.extend(["", f"**{title}**", "", "| Severity | Issue | Location |", "|---|---|---|"])
        for n, issue in enumerate(issues[:max_issues]):
            sev = issue["severity"]
            extra = f" ({note[n]})" if note else ""
            lines.append(
                f"| {_SEVERITY_ICON.get(sev, '')} {sev} | {_inert(issue['title'])}{_count(issue)}"
                f"{extra} | {_inert(_location(issue)) or '-'} |"
            )
        if len(issues) > max_issues:
            lines.extend(["", f"…and {len(issues) - max_issues} more."])

    table("New", diff["new_issues"])
    worse = diff["worsened_issues"]
    table(
        "Worse",
        [w["issue"] for w in worse],
        [f"was {w['base_severity']}, ×{w['base_occurrences']}" for w in worse],
    )
    table("Fixed", diff["fixed_issues"])
    if diff.get("deep_categories"):
        lines.extend(["", "Investigated with tools: " + ", ".join(diff["deep_categories"]) + "."])
    lines.extend(["", f"<sub>DrRepo {_inert(diff.get('drrepo_version', ''))}</sub>"])
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
        rule_id = rule_key(issue.get("source") or issue["category"], issue.get("rule_id"))
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

    # Suppressed issues stay visible to code scanning, marked with SARIF's native
    # `suppressions` (GitHub hides them from the default alert view).
    for entry in report.get("suppressed", []):
        issue, suppression = entry["issue"], entry["suppression"]
        rid = rule_key(issue.get("source") or issue["category"], issue.get("rule_id"))
        rules.setdefault(
            rid,
            {
                "id": rid,
                "name": rid.replace("/", "_").replace(":", "_"),
                "shortDescription": {"text": issue["title"][:120]},
                "help": {"text": issue.get("recommendation", "")},
                "properties": {"category": issue["category"], "tags": [issue["category"]]},
            },
        )
        result: dict[str, Any] = {
            "ruleId": rid,
            "level": _SARIF_LEVEL.get(issue["severity"], "warning"),
            "message": {"text": f"{issue['title']}: {issue.get('description', '')}".strip()[:1000]},
            "suppressions": [
                {
                    "kind": "external",
                    "status": "accepted",
                    "justification": f"{suppression['reason']} ({suppression['origin']})",
                }
            ],
        }
        if issue.get("file"):
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": issue["file"], "uriBaseId": "%SRCROOT%"},
                        "region": {"startLine": max(1, int(issue.get("line") or 1))},
                    }
                }
            ]
        results.append(result)

    run: dict[str, Any] = {
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
    repo = report.get("repository", {})
    if repo.get("commit_sha"):
        # Ties every result to the exact commit analyzed (SARIF 2.1.0 section 3.23).
        provenance = {"repositoryUri": repo.get("url", ""), "revisionId": repo["commit_sha"]}
        if repo.get("ref"):
            provenance["branch"] = repo["ref"]
        run["versionControlProvenance"] = [provenance]
    provenance = report.get("provenance") or {}
    if provenance:
        run["properties"] = {"drrepo": provenance}  # SARIF property bag: what produced this run
    sarif = {"$schema": SARIF_SCHEMA_URL, "version": "2.1.0", "runs": [run]}
    return json.dumps(sarif, indent=2, ensure_ascii=False)


# Package URL types (https://github.com/package-url/purl-spec) per OSV ecosystem.
_PURL_TYPES = {
    "PyPI": "pypi",
    "npm": "npm",
    "Go": "golang",
    "crates.io": "cargo",
    "RubyGems": "gem",
    "NuGet": "nuget",
    "Packagist": "composer",
    "Maven": "maven",
}


def purl(ecosystem: str, name: str, version: str) -> str | None:
    kind = _PURL_TYPES.get(ecosystem)
    if kind is None:
        return None
    if kind == "pypi":
        name = name.lower().replace("_", "-")
    if kind == "maven" and ":" in name:
        group, artifact = name.split(":", 1)
        path = f"{quote(group, safe='.')}/{quote(artifact, safe='.')}"
    elif kind in ("npm", "golang", "composer") and "/" in name:
        namespace, short = name.rsplit("/", 1)
        path = (
            "/".join(quote(p, safe=".") for p in namespace.split("/"))
            + f"/{quote(short, safe='.')}"
        )
    else:
        path = quote(name, safe=".")
    return f"pkg:{kind}/{path}@{quote(version, safe='.')}"


_SPDX_EXPRESSION = re.compile(
    r"^\(?[A-Za-z0-9.+-]+(?:\s+(?:AND|OR|WITH)\s+\(?[A-Za-z0-9.+-]+\)?)*\)?$"
)


def _cyclonedx_license(license_text: str) -> dict[str, Any]:
    """An SPDX-shaped license as an `expression` (valid for a single id too), else a `name`.

    `license.id` would have to be in CycloneDX's SPDX enum, which registry metadata
    doesn't guarantee, so ids are never emitted bare.
    """
    if _SPDX_EXPRESSION.match(license_text.strip()):
        return {"expression": license_text.strip()}
    return {"license": {"name": license_text}}


def to_cyclonedx(report: dict[str, Any]) -> str:
    """CycloneDX 1.6 SBOM of the analyzed repository's dependencies, with OSV advisories.

    Built from `report["dependencies"]` (manifests and lockfiles, never an install),
    so it lists what the repository declares at the analyzed commit.
    """
    from drrepo import __version__

    repo = report.get("repository", {})
    components = []
    refs: dict[tuple[str, str, str], str] = {}
    for dep in report.get("dependencies", []):
        ref = purl(dep["ecosystem"], dep["name"], dep["version"]) or (
            f"{dep['ecosystem']}:{dep['name']}@{dep['version']}"
        )
        refs[(dep["ecosystem"], dep["name"], dep["version"])] = ref
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": ref,
            "name": dep["name"],
            "version": dep["version"],
            "scope": "required" if dep["scope"] == "runtime" else "optional",
        }
        if ref.startswith("pkg:"):
            component["purl"] = ref
        if dep.get("license"):
            component["licenses"] = [_cyclonedx_license(dep["license"])]
        components.append(component)

    vulnerabilities = []
    issues_by_rule = {
        i.get("rule_id"): i for i in report.get("issues", []) if i.get("source") == "osv.dev"
    }
    advisories: dict[str, list[str]] = {}
    for dep in report.get("dependencies", []):
        for vuln_id in dep.get("vulnerabilities", []):
            advisories.setdefault(vuln_id, []).append(
                refs[(dep["ecosystem"], dep["name"], dep["version"])]
            )
    for vuln_id, affected in sorted(advisories.items()):
        entry: dict[str, Any] = {
            "bom-ref": f"vuln:{vuln_id}",
            "id": vuln_id,
            "source": {"name": "OSV", "url": f"https://osv.dev/vulnerability/{vuln_id}"},
            "affects": [{"ref": ref} for ref in sorted(set(affected))],
        }
        issue = issues_by_rule.get(vuln_id)
        if issue:
            entry["ratings"] = [{"source": {"name": "DrRepo"}, "severity": issue["severity"]}]
            entry["recommendation"] = issue.get("recommendation", "")
        vulnerabilities.append(entry)

    sha = repo.get("commit_sha")
    # Deterministic: the same repository at the same commit yields the same serial number.
    seed = f"{repo.get('url', '')}@{sha or report.get('generated_at', '')}"
    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}",
        "version": 1,
        "metadata": {
            "timestamp": report.get("generated_at") or None,
            "tools": {
                "components": [{"type": "application", "name": "DrRepo", "version": __version__}]
            },
            "component": {
                "type": "application",
                "bom-ref": "repository",
                "name": repo.get("full_name") or repo.get("name", "repository"),
                **({"version": sha} if sha else {}),
                "externalReferences": [{"type": "vcs", "url": repo.get("url", "")}],
            },
        },
        "components": components,
    }
    if not bom["metadata"]["timestamp"]:
        del bom["metadata"]["timestamp"]
    if vulnerabilities:
        bom["vulnerabilities"] = vulnerabilities
    return json.dumps(bom, indent=2, ensure_ascii=False)


EXPORTERS = {
    "json": to_json,
    "md": to_markdown,
    "sarif": to_sarif,
    "cdx": to_cyclonedx,
    "summary": to_summary,
}
# File extension per format; CycloneDX's convention is `.cdx.json`.
EXTENSIONS = {
    "json": "json",
    "md": "md",
    "sarif": "sarif",
    "cdx": "cdx.json",
    "summary": "summary.md",
}
