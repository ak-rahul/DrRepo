"""Shared data models for DrRepo v2.

These are the contracts between collectors (deterministic, no LLM) and analyst
agents (LLM-based). Collectors only ever produce `CollectorResult`; analysts
only ever produce `Issue` lists. Nothing else crosses that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    """Issue severity, ordered from most to least urgent."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    """The five scored evaluation dimensions."""

    DOCUMENTATION = "documentation"
    CODE_QUALITY = "code_quality"
    SECURITY = "security"
    DEPENDENCIES = "dependencies"
    MAINTAINABILITY = "maintainability"


class CollectorStatus(str, Enum):
    """Outcome of running a single collector, surfaced in the final report."""

    OK = "ok"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class CollectorResult:
    """Uniform output shape for every collector.

    `data` holds collector-specific structured findings (schema documented in
    each collector module). `status`/`detail` let the pipeline degrade
    gracefully instead of crashing when a tool isn't available or a repo is
    unsupported.
    """

    name: str
    status: CollectorStatus
    data: dict[str, Any] = field(default_factory=dict)
    detail: Optional[str] = None


@dataclass
class Issue:
    """A single actionable finding surfaced in the report."""

    severity: Severity
    category: Category
    title: str
    description: str
    recommendation: str
    file: Optional[str] = None
    line: Optional[int] = None
    source: Optional[str] = None  # which collector/tool produced this, e.g. "bandit"


@dataclass
class CategoryScore:
    category: Category
    score: float  # 0-100
    summary: str
    issues: list[Issue] = field(default_factory=list)


@dataclass
class Report:
    """Final synthesized output of an analysis run."""

    repository: dict[str, Any]
    overall_score: float
    category_scores: dict[str, CategoryScore]
    issues: list[Issue]
    quick_wins: list[str]
    collector_status: dict[str, dict[str, Optional[str]]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain JSON-able dict."""
        return {
            "repository": self.repository,
            "overall_score": round(self.overall_score, 1),
            "category_scores": {
                name: {
                    "category": cs.category.value,
                    "score": round(cs.score, 1),
                    "summary": cs.summary,
                    "issues": [issue_to_dict(i) for i in cs.issues],
                }
                for name, cs in self.category_scores.items()
            },
            "issues": [issue_to_dict(i) for i in self.issues],
            "quick_wins": self.quick_wins,
            "collector_status": self.collector_status,
        }


def issue_to_dict(issue: Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "category": issue.category.value,
        "title": issue.title,
        "description": issue.description,
        "recommendation": issue.recommendation,
        "file": issue.file,
        "line": issue.line,
        "source": issue.source,
    }
