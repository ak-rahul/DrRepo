"""Domain types shared by every layer.

Recon collectors produce `CollectorResult`s; analysts and investigators produce
`CategoryFinding`s built from `Issue`s; the synthesizer turns those into one
`Report`. LangGraph state holds these objects directly (nothing is persisted
mid-run); `to_dict()` exists only for the final report and its exporters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

# Version of the `Report.to_dict()` contract (report/report.schema.json).
# Minor bump: a new optional field. Major bump: a removed, renamed, or retyped field.
REPORT_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------- repository ---

_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$")


@dataclass(frozen=True)
class RepoRef:
    """A validated public GitHub repository reference.

    `parse()` accepts what people paste -- `https://github.com/o/r`, `.../o/r.git`,
    `.../o/r/tree/main/sub`, `github.com/o/r` -- and rejects everything else. Only
    the normalized `clone_url` ever reaches `git`.
    """

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.full_name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.full_name}.git"

    @classmethod
    def parse(cls, url: str) -> RepoRef:
        """Raises ValueError (user-presentable) for anything but a github.com repo URL."""
        raw = (url or "").strip()
        if not raw:
            raise ValueError("Repository URL cannot be empty")
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("https", "http") or host not in ("github.com", "www.github.com"):
            raise ValueError("Only https://github.com/<owner>/<repo> URLs are supported")
        if parsed.username or parsed.password:
            raise ValueError("Repository URLs must not contain credentials")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError("Expected a URL of the form https://github.com/<owner>/<repo>")
        owner, name = parts[0], parts[1].removesuffix(".git")
        if (
            not _GITHUB_NAME_RE.match(owner)
            or not _GITHUB_NAME_RE.match(name)
            or name in (".", "..")
        ):
            raise ValueError(f"'{owner}/{name}' is not a valid GitHub repository name")
        return cls(owner=owner, name=name)


# ------------------------------------------------------------ findings ---


class Severity(StrEnum):
    """Issue severity, ordered from most to least urgent."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @classmethod
    def parse(cls, raw: str | None, default: Severity | None = None) -> Severity:
        """Lenient parse for tool/LLM output ("ERROR", "Moderate", "urgent"...)."""
        value = (raw or "").strip().lower()
        aliases = {
            "error": cls.HIGH,
            "moderate": cls.MEDIUM,
            "warning": cls.MEDIUM,
            "info": cls.LOW,
            "note": cls.LOW,
        }
        if value in cls._value2member_map_:
            return cls(value)
        if value in aliases:
            return aliases[value]
        return default if default is not None else cls.MEDIUM


_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


class Category(StrEnum):
    """The five scored evaluation dimensions."""

    DOCUMENTATION = "documentation"
    CODE_QUALITY = "code_quality"
    SECURITY = "security"
    DEPENDENCIES = "dependencies"
    MAINTAINABILITY = "maintainability"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class CollectorStatus(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    ERROR = "error"


class InvestigationDepth(StrEnum):
    """How a category was analyzed: one narrative call, or a tool-calling loop."""

    SHALLOW = "shallow"
    DEEP = "deep"


@dataclass
class CollectorResult:
    """Uniform output of every collector. `data`'s schema is documented per collector."""

    name: str
    status: CollectorStatus
    data: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == CollectorStatus.OK

    @classmethod
    def skipped(cls, name: str, detail: str) -> CollectorResult:
        return cls(name=name, status=CollectorStatus.SKIPPED, detail=detail)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "data": self.data, "detail": self.detail}


def rule_key(source: str, rule_id: str | None) -> str:
    """The stable rule id shared by SARIF and suppressions: `<source>/<rule_id>`, or the
    bare source for checks without a rule id (e.g. `readme_analyzer`)."""
    return f"{source}/{rule_id}" if rule_id else source


@dataclass
class Location:
    file: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line}


@dataclass
class Issue:
    """One actionable finding. Repeated findings of the same rule are aggregated
    into a single Issue with `occurrences` > 1 and up to N sample `locations`."""

    severity: Severity
    category: Category
    title: str
    description: str
    recommendation: str
    source: str  # which collector/tool produced it, e.g. "bandit"; doubles as SARIF rule family
    rule_id: str | None = None  # tool-specific check code, e.g. "B602" or "F821"
    locations: list[Location] = field(default_factory=list)
    occurrences: int = 1

    @property
    def file(self) -> str | None:
        return self.locations[0].file if self.locations else None

    @property
    def line(self) -> int | None:
        return self.locations[0].line if self.locations else None

    def dedupe_key(self) -> tuple[str, str, str | None, int | None]:
        return (self.category.value, self.title.lower(), self.file, self.line)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "recommendation": self.recommendation,
            "source": self.source,
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "locations": [loc.to_dict() for loc in self.locations],
            "occurrences": self.occurrences,
        }


@dataclass
class ToolCallTrace:
    """One tool call an investigator made. `observation` is the (truncated) tool
    output, so a reader can verify claims came from real evidence."""

    tool: str
    tool_input: dict[str, Any]
    observation: str

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "tool_input": self.tool_input, "observation": self.observation}


@dataclass
class CategoryFinding:
    """One category's result, whether produced by the shallow or deep path.

    `assessed=False` means the category could not be evaluated (its inputs were
    unavailable); its score is then excluded from the overall weighted score
    instead of dragging it toward an arbitrary midpoint.
    """

    category: Category
    score: float
    summary: str
    issues: list[Issue] = field(default_factory=list)
    assessed: bool = True
    investigation_depth: InvestigationDepth = InvestigationDepth.SHALLOW
    investigation_trace: list[ToolCallTrace] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Issues excluded by a suppression: [{"issue": Issue.to_dict(), "suppression": {...}}]
    suppressed: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "score": round(self.score, 1),
            "summary": self.summary,
            "assessed": self.assessed,
            "issues": [i.to_dict() for i in self.issues],
            "investigation_depth": self.investigation_depth.value,
            "investigation_trace": [t.to_dict() for t in self.investigation_trace],
            "notes": list(self.notes),
            "suppressed": list(self.suppressed),
        }


@dataclass
class CategoryPlan:
    """The Lead Investigator's decision for one category."""

    category: Category
    depth: InvestigationDepth
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"depth": self.depth.value, "rationale": self.rationale}


@dataclass
class InvestigationPlan:
    """The Lead Investigator's per-repo plan: one `CategoryPlan` per category."""

    plans: dict[str, CategoryPlan]

    def depth_for(self, category: Category) -> InvestigationDepth:
        plan = self.plans.get(category.value)
        return plan.depth if plan else InvestigationDepth.SHALLOW

    def to_dict(self) -> dict[str, Any]:
        return {name: plan.to_dict() for name, plan in self.plans.items()}

    @classmethod
    def all_shallow(cls, rationale: str) -> InvestigationPlan:
        return cls(
            plans={
                c.value: CategoryPlan(
                    category=c, depth=InvestigationDepth.SHALLOW, rationale=rationale
                )
                for c in Category
            }
        )


@dataclass
class Report:
    """Final synthesized output of an analysis run."""

    repository: dict[str, Any]
    overall_score: float
    category_scores: dict[str, CategoryFinding]
    issues: list[Issue]
    quick_wins: list[str]
    collector_status: dict[str, dict[str, str | None]]
    investigation_plan: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    drrepo_version: str = ""
    # Package inventory: [{ecosystem, name, version, scope, license, vulnerabilities}]
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    def issue_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for issue in self.issues:
            counts[issue.severity.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-able dict -- the one shape every exporter and UI consumes.

        Its contract is `report/report.schema.json` (see `report.schema.validate`).
        """
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "repository": self.repository,
            "overall_score": round(self.overall_score, 1),
            "generated_at": self.generated_at,
            "drrepo_version": self.drrepo_version,
            "issue_counts": self.issue_counts(),
            "category_scores": {name: cs.to_dict() for name, cs in self.category_scores.items()},
            "issues": [i.to_dict() for i in self.issues],
            "suppressed": [s for cs in self.category_scores.values() for s in cs.suppressed],
            "quick_wins": self.quick_wins,
            "dependencies": self.dependencies,
            "investigation_plan": self.investigation_plan,
            "collector_status": self.collector_status,
        }
