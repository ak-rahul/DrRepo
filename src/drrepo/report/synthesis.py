"""Turn category findings into one scored `Report`.

Pure: no I/O, no LLM, no clock (the caller passes `generated_at`), so the same
findings always produce the same report.
"""

from __future__ import annotations

from typing import Any

from drrepo.models import Category, CategoryFinding, InvestigationPlan, Issue, Report, Severity

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
    dependencies: list[dict[str, Any]] | None = None,
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
        dependencies=dependencies or [],
    )


def dependency_inventory(audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Packages from the dependency audit, with license and advisory ids merged in."""
    if not audit:
        return []
    licenses = {
        (lic["ecosystem"], lic["package"], lic["version"]): lic.get("license")
        for lic in audit.get("licenses", [])
    }
    advisories: dict[tuple[str, str, str], list[str]] = {}
    for v in audit.get("vulnerabilities", []):
        advisories.setdefault((v["ecosystem"], v["package"], v["version"]), []).append(v["vuln_id"])
    return [
        {
            **pkg,
            "license": licenses.get((pkg["ecosystem"], pkg["name"], pkg["version"])),
            "vulnerabilities": advisories.get((pkg["ecosystem"], pkg["name"], pkg["version"]), []),
        }
        for pkg in audit.get("packages", [])
    ]


def grade(score: float) -> str:
    """Letter grade for display."""
    for threshold, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= threshold:
            return letter
    return "F"
