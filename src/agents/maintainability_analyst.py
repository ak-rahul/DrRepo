"""Maintainability analyst: repo structure/hygiene + activity signals."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict

_SYSTEM_PROMPT = """You are a senior engineer assessing the long-term maintainability of a \
repository. Given structural facts (tests, CI, license, activity recency), write a concise, \
honest narrative (3-5 sentences). Do not invent facts you weren't given."""

_STALE_DAYS_THRESHOLD = 365


def _structure_issues(file_structure: Dict[str, bool], stars: int) -> list[Issue]:
    issues = []
    if not file_structure.get("has_tests", False):
        issues.append(
            Issue(
                severity=Severity.HIGH,
                category=Category.MAINTAINABILITY,
                title="No test directory detected",
                description="No tests/, test/, __tests__, or spec directory was found.",
                recommendation="Add an automated test suite.",
                source="github_metadata",
            )
        )
    if not file_structure.get("has_ci", False):
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.MAINTAINABILITY,
                title="No CI/CD configuration detected",
                description="No .github, .travis.yml, .circleci, or similar CI config was found.",
                recommendation="Add a CI pipeline to run tests/lint on every push.",
                source="github_metadata",
            )
        )
    if not file_structure.get("has_license", False):
        issues.append(
            Issue(
                severity=Severity.HIGH,
                category=Category.MAINTAINABILITY,
                title="No license detected",
                description="No LICENSE file was found in the repository root.",
                recommendation="Add an OSS license so others know how they may use this project.",
                source="github_metadata",
            )
        )
    if not file_structure.get("has_contributing", False) and stars > 50:
        issues.append(
            Issue(
                severity=Severity.LOW,
                category=Category.MAINTAINABILITY,
                title="No contributing guide",
                description="No CONTRIBUTING file was found, despite the project having community interest.",
                recommendation="Add a CONTRIBUTING.md explaining how to set up and submit changes.",
                source="github_metadata",
            )
        )
    return issues


def _staleness_issue(pushed_at: str) -> Issue | None:
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    days_since_push = (datetime.now(timezone.utc) - pushed).days
    if days_since_push > _STALE_DAYS_THRESHOLD:
        return Issue(
            severity=Severity.MEDIUM,
            category=Category.MAINTAINABILITY,
            title="Repository appears inactive",
            description=f"Last push was {days_since_push} days ago.",
            recommendation="Confirm whether this project is still maintained; if not, say so in the README.",
            source="github_metadata",
        )
    return None


def _score(issues: list[Issue]) -> float:
    if not issues:
        return 100.0
    penalty = sum(
        {"critical": 25, "high": 15, "medium": 8, "low": 3}[i.severity.value] for i in issues
    )
    return max(0.0, 100.0 - penalty)


class MaintainabilityAnalyst(BaseAnalystAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__("MaintainabilityAnalyst", _SYSTEM_PROMPT, llm_client)

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        github_data = collector_results.get("github_metadata", {})
        file_structure = github_data.get("file_structure", {})
        stars = github_data.get("stars", 0)

        issues = _structure_issues(file_structure, stars)
        stale_issue = _staleness_issue(github_data.get("pushed_at", ""))
        if stale_issue:
            issues.append(stale_issue)

        score = _score(issues)

        prompt = (
            f"Repository structure: {file_structure}\n"
            f"Stars: {stars}, Open issues: {github_data.get('open_issues', 0)}\n"
            f"Last pushed: {github_data.get('pushed_at', 'unknown')}\n\n"
            "Summarize the maintainability of this repository."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
