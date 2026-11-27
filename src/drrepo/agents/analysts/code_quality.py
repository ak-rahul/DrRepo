"""Code-quality analyst: ruff findings, normalized by code size."""

from __future__ import annotations

from typing import Any

from drrepo.agents.analysts.base import (
    NARRATIVE_RULES,
    Analyst,
    Assessment,
    Recon,
    aggregate,
    collector_data,
    collector_detail,
    decay_score,
    issue_penalty,
)
from drrepo.models import Category, Severity

# Real bugs (undefined names, syntax errors, broken comparisons) vs. likely bugs
# (bugbear) vs. hygiene (unused imports/variables, style).
_HIGH_PREFIXES = ("E9", "F63", "F7", "F82", "PLE", "syntax-error")
_MEDIUM_PREFIXES = ("B", "F50", "F52", "F60")
# Penalty per 1k lines of Python that maps to ~37/100.
_PENALTY_PER_KLOC_SCALE = 30.0
_ABSOLUTE_SCALE = 80.0


def ruff_severity(finding: dict[str, Any]) -> Severity:
    rule = str(finding.get("rule") or "")
    if rule.startswith(_HIGH_PREFIXES):
        return Severity.HIGH
    if rule.startswith(_MEDIUM_PREFIXES):
        return Severity.MEDIUM
    return Severity.LOW


def _title(finding: dict[str, Any], count: int) -> str:
    rule = finding.get("rule")
    message = (finding.get("message") or "").split("\n")[0][:80]
    return f"{rule}: {message}" if count == 1 else f"{rule} ({count} occurrences)"


def _recommendation(finding: dict[str, Any]) -> str:
    url = finding.get("url")
    return f"Fix the {finding.get('rule')} findings" + (f" (see {url})." if url else ".")


class CodeQualityAnalyst(Analyst):
    category = Category.CODE_QUALITY
    narrative_prompt = (
        "You are a senior code reviewer summarizing static-analysis results. " + NARRATIVE_RULES
    )
    investigation_prompt = (
        "You are investigating code quality. The ruff findings listed are already reported -- "
        "do not repeat them. Look for problems a linter misses: very long or deeply nested "
        "functions, duplicated logic, swallowed exceptions, missing error handling at I/O "
        "boundaries, dead code, and confusing module structure. Use run_scanner_on_path to "
        "look closer at hot spots. Every issue must cite a file (and line where possible)."
    )
    tool_families = ("files", "scanners")
    rescore_scale = 60.0

    def assess(self, recon: Recon) -> Assessment:
        static = collector_data(recon, "static_analysis")
        layout = collector_data(recon, "repo_layout") or {}
        python_lines = int(layout.get("python_lines") or 0)

        if static is None:
            detail = collector_detail(recon, "static_analysis", "static analysis did not run")
            return self.unassessed(f"Code quality could not be assessed: {detail}.")
        if layout and python_lines == 0:
            languages = (
                ", ".join(list(layout.get("lines_by_language", {}))[:3]) or "no recognized source"
            )
            return self.unassessed(
                f"Code quality not scored: automated linting covers Python, and this repository "
                f"contains {languages}."
            )

        findings = static.get("findings", [])
        issues = aggregate(
            findings,
            category=self.category,
            severity_of=ruff_severity,
            title_of=_title,
            recommendation_of=_recommendation,
        )
        penalty = issue_penalty(issues)
        if python_lines:
            kloc = max(python_lines / 1000.0, 1.0)
            score = decay_score(penalty / kloc, _PENALTY_PER_KLOC_SCALE)
        else:
            score = decay_score(penalty, _ABSOLUTE_SCALE)

        size = f" across {python_lines:,} lines of Python" if python_lines else ""
        if not findings:
            return Assessment(
                issues=[], score=100.0, summary=f"ruff found no bug-class issues{size}."
            )

        top = ", ".join(f"{i.rule_id} x{i.occurrences}" for i in issues[:6])
        high = sum(i.occurrences for i in issues if i.severity == Severity.HIGH)
        summary = f"ruff reported {len(findings)} findings in {len(issues)} rule groups{size}; {high} are likely bugs. Most frequent: {top}."
        facts = f"{summary}\nTop issue groups:\n" + "\n".join(
            f"- [{i.severity.value}] {i.title} (e.g. {i.file}:{i.line})" for i in issues[:10]
        )
        return Assessment(issues=issues, score=score, summary=summary, narrative_facts=facts)
