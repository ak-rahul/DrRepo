"""Security analyst: bandit, semgrep, and secret-scan findings."""

from __future__ import annotations

import math
from typing import Any

from drrepo.agents.analysts.base import (
    Analyst,
    Assessment,
    Recon,
    aggregate,
    collector_data,
    collector_detail,
    decay_score,
    issue_penalty,
)
from drrepo.models import Category, Issue, Severity

_SCALE = 40.0
# CI workflow and container findings (recon/infrastructure.py) are scored on a
# gentler, bounded curve: they can take at most INFRA_MAX_IMPACT off the code
# security score, so hardening gaps never outweigh flaws in the code itself.
INFRA_SOURCES = frozenset({"zizmor", "hadolint", "drrepo", "scorecard"})
INFRA_MAX_IMPACT = 0.4
_INFRA_SCALE = 60.0


def security_score(issues: list[Issue]) -> float:
    code = [i for i in issues if i.source not in INFRA_SOURCES]
    infra = [i for i in issues if i.source in INFRA_SOURCES]
    infra_factor = 1 - INFRA_MAX_IMPACT * (1 - math.exp(-issue_penalty(infra) / _INFRA_SCALE))
    return round(decay_score(issue_penalty(code), _SCALE) * infra_factor, 1)


def security_severity(finding: dict[str, Any]) -> Severity:
    tool = finding.get("tool")
    severity = Severity.parse(finding.get("severity"), default=Severity.MEDIUM)
    if tool == "bandit" and str(finding.get("confidence") or "").upper() == "LOW":
        # Low-confidence bandit hits are frequently false positives; drop one level.
        severity = {Severity.CRITICAL: Severity.HIGH, Severity.HIGH: Severity.MEDIUM}.get(
            severity, Severity.LOW
        )
    return severity


def dedupe_cross_tool(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop semgrep hits on a file:line bandit already flagged (they often overlap,
    e.g. both report the same weak-hash call); bandit's rule ids are more specific."""
    bandit_locations = {
        (f.get("file"), f.get("line")) for f in findings if f.get("tool") == "bandit"
    }
    return [
        f
        for f in findings
        if not (f.get("tool") == "semgrep" and (f.get("file"), f.get("line")) in bandit_locations)
    ]


def _title(finding: dict[str, Any], count: int) -> str:
    tool, rule = finding.get("tool"), finding.get("rule")
    if tool == "secret_scan":
        return f"Possible {rule} committed to source" + (
            f" ({count} locations)" if count > 1 else ""
        )
    label = str(rule).rsplit(".", 1)[-1] if tool == "semgrep" else rule
    message = (finding.get("message") or "").split("\n")[0][:70]
    return f"{tool} {label}: {message}" if count == 1 else f"{tool} {label} ({count} occurrences)"


def _recommendation(finding: dict[str, Any]) -> str:
    if finding.get("tool") == "secret_scan" and "test/fixture" in (finding.get("message") or ""):
        return "Confirm this is a throwaway test credential that grants no real access; if not, rotate it."
    if finding.get("tool") == "secret_scan":
        return (
            "Revoke and rotate the credential now, move it to an environment variable or secret "
            "store, and purge it from git history (e.g. git filter-repo)."
        )
    url = finding.get("url")
    return f"Review each {finding.get('tool')} {finding.get('rule')} hit and fix or justify it" + (
        f" (see {url})." if url else "."
    )


class SecurityAnalyst(Analyst):
    category = Category.SECURITY
    tool_families = ("files", "symbols", "scanners", "git_history")
    rescore_scale = _SCALE

    def score_issues(self, recon: Recon, issues: list[Issue]) -> float | None:
        return security_score(issues) if issues else 100.0

    def assess(self, recon: Recon) -> Assessment:
        security = collector_data(recon, "security")
        if security is None:
            detail = collector_detail(recon, "security", "security scanners did not run")
            return self.unassessed(f"Security could not be assessed: {detail}.")

        infrastructure = collector_data(recon, "infrastructure") or {}
        scorecard = collector_data(recon, "scorecard") or {}
        findings = (
            dedupe_cross_tool(security.get("findings", []))
            + [f for f in infrastructure.get("findings", []) if f.get("category") == "security"]
            + scorecard.get("findings", [])
        )
        tool_status = {
            **security.get("tool_status", {}),
            **{
                tool: s
                for tool, s in infrastructure.get("tool_status", {}).items()
                if not s.startswith("skipped: no ")  # a repo without workflows isn't a problem
            },
        }
        ran = ", ".join(t for t, s in tool_status.items() if s == "ok") or "none"
        issues = aggregate(
            findings,
            category=self.category,
            severity_of=security_severity,
            title_of=_title,
            recommendation_of=_recommendation,
        )
        notes = [f"{tool}: {status}" for tool, status in tool_status.items() if status != "ok"]
        analyzed = (collector_data(recon, "repo_clone") or {}).get("commit_sha")
        scanned = scorecard.get("scanned_commit")
        if scorecard.get("findings") and analyzed and scanned and scanned != analyzed:
            notes.append(
                f"OpenSSF Scorecard findings describe commit {scanned[:12]} (its last scan on "
                f"{scorecard.get('date', '?')}), not the analyzed commit {analyzed[:12]}."
            )
        if not issues:
            return Assessment(
                issues=[], score=100.0, summary=f"No security findings from: {ran}.", notes=notes
            )

        secrets = sum(i.occurrences for i in issues if i.source == "secret_scan")
        counts = {s.value: sum(i.occurrences for i in issues if i.severity == s) for s in Severity}
        summary = (
            f"Scanners ({ran}) reported {sum(i.occurrences for i in issues)} findings: "
            + ", ".join(f"{n} {sev}" for sev, n in counts.items() if n)
            + (f"; {secrets} possible committed secret(s)." if secrets else ".")
        )
        facts = f"{summary}\nTop findings:\n" + "\n".join(
            f"- [{i.severity.value}] {i.title} ({i.file}:{i.line})" for i in issues[:10]
        )
        return Assessment(
            issues=issues,
            score=security_score(issues),
            summary=summary,
            narrative_facts=facts,
            notes=notes,
        )
