"""Merges per-category analyst findings into one final Report."""

from __future__ import annotations

from typing import Any, Dict

from src.models import Category, CategoryScore, Issue, Report, Severity

_CATEGORY_WEIGHTS = {
    Category.DOCUMENTATION: 0.15,
    Category.CODE_QUALITY: 0.25,
    Category.SECURITY: 0.30,
    Category.DEPENDENCIES: 0.15,
    Category.MAINTAINABILITY: 0.15,
}

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def _issue_from_dict(d: Dict[str, Any]) -> Issue:
    return Issue(
        severity=Severity(d["severity"]),
        category=Category(d["category"]),
        title=d["title"],
        description=d["description"],
        recommendation=d["recommendation"],
        file=d.get("file"),
        line=d.get("line"),
        source=d.get("source"),
    )


def synthesize_report(
    repository: Dict[str, Any],
    category_findings: Dict[str, Any],
    collector_status: Dict[str, Dict[str, Any]],
) -> Report:
    """Build the final Report from per-category analyst output.

    `category_findings` keys are Category values; each value is
    `{"summary": str, "score": float, "issues": [Issue-as-dict]}`.
    """
    category_scores: Dict[str, CategoryScore] = {}
    all_issues: list[Issue] = []
    weighted_total = 0.0
    weight_sum = 0.0

    for category in Category:
        finding = category_findings.get(category.value)
        if finding is None:
            continue

        issues = [_issue_from_dict(i) for i in finding.get("issues", [])]
        score = float(finding.get("score", 0.0))

        category_scores[category.value] = CategoryScore(
            category=category, score=score, summary=finding.get("summary", ""), issues=issues
        )
        all_issues.extend(issues)

        weight = _CATEGORY_WEIGHTS[category]
        weighted_total += score * weight
        weight_sum += weight

    overall_score = weighted_total / weight_sum if weight_sum else 0.0

    all_issues.sort(key=lambda i: _SEVERITY_ORDER[i.severity])

    quick_wins = [
        i.recommendation for i in all_issues if i.severity in (Severity.LOW, Severity.MEDIUM)
    ][:5]

    return Report(
        repository=repository,
        overall_score=overall_score,
        category_scores=category_scores,
        issues=all_issues,
        quick_wins=quick_wins,
        collector_status=collector_status,
    )
