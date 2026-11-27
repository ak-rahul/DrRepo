"""The analyst contract every report category implements.

Division of labour (the core design rule of DrRepo):
- **Deterministic first.** `assess()` turns collector output into `Issue`s and a
  score with plain code. File, line, rule, and severity always come from a real
  tool, never from LLM text, and the result is reproducible.
- **The LLM narrates, it doesn't decide.** On the shallow path the only LLM call
  writes the summary paragraph. If that call fails (quota, circuit open, network)
  the deterministic summary is used and the run carries on.
- **Deep investigation adds evidence.** On the deep path the investigator's
  issues are merged with the deterministic ones and the analyst re-scores the
  union with `rescore()` -- recon findings are never discarded.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from drrepo.agents import prompts
from drrepo.agents.llm import LLMRuntime
from drrepo.log import logger
from drrepo.models import (
    Category,
    CategoryFinding,
    CollectorResult,
    InvestigationDepth,
    Issue,
    Location,
    Severity,
)

Recon = dict[str, CollectorResult]  # collector name -> result

SEVERITY_WEIGHTS = {
    Severity.CRITICAL: 25.0,
    Severity.HIGH: 10.0,
    Severity.MEDIUM: 4.0,
    Severity.LOW: 1.0,
}
MAX_SAMPLE_LOCATIONS = 20


def collector_data(recon: Recon, name: str) -> dict[str, Any] | None:
    """`data` for collector `name` if it ran successfully, else None."""
    result = recon.get(name)
    return result.data if result is not None and result.ok else None


def collector_detail(recon: Recon, name: str, default: str) -> str:
    """Why collector `name` produced no data (its `detail`), or `default`."""
    result = recon.get(name)
    return (result.detail if result is not None else None) or default


def issue_penalty(issues: Iterable[Issue]) -> float:
    """Severity-weighted penalty with diminishing returns for repeats.

    An aggregated issue with N occurrences costs `weight * (1 + log2(N))`: the
    50th unused import says much less about a codebase than the first one did.
    """
    return sum(
        SEVERITY_WEIGHTS[i.severity] * (1 + math.log2(max(1, i.occurrences))) for i in issues
    )


def decay_score(penalty: float, scale: float, base: float = 100.0) -> float:
    """Map a penalty onto (0, base]: `scale` points of penalty -> ~37% of base."""
    return round(base * math.exp(-max(0.0, penalty) / scale), 1)


def aggregate(
    findings: Iterable[dict[str, Any]],
    *,
    category: Category,
    severity_of: Callable[[dict[str, Any]], Severity],
    title_of: Callable[[dict[str, Any], int], str],
    recommendation_of: Callable[[dict[str, Any]], str],
) -> list[Issue]:
    """Group raw findings by (tool, rule, severity) into one Issue per group."""
    groups: dict[tuple[str, str, Severity], list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        groups[(f.get("tool") or "unknown", f.get("rule") or "finding", severity_of(f))].append(f)

    issues = []
    for (tool, rule, severity), items in groups.items():
        first = items[0]
        files = {f.get("file") for f in items if f.get("file")}
        description = first.get("message") or "No message provided"
        if len(items) > 1:
            description += f" ({len(items)} occurrences across {len(files)} file(s))"
        issues.append(
            Issue(
                severity=severity,
                category=category,
                title=title_of(first, len(items)),
                description=description,
                recommendation=recommendation_of(first),
                source=tool,
                rule_id=rule,
                locations=[
                    Location(file=f["file"], line=f.get("line"))
                    for f in items[:MAX_SAMPLE_LOCATIONS]
                    if f.get("file")
                ],
                occurrences=len(items),
            )
        )
    return sort_issues(issues)


def sort_issues(issues: Iterable[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (i.severity.rank, -i.occurrences, i.title))


def merge_issues(base: list[Issue], extra: list[Issue]) -> list[Issue]:
    """Union of two issue lists, dropping `extra` items that duplicate `base`."""
    seen = {i.dedupe_key() for i in base}
    merged = list(base)
    for issue in extra:
        if issue.dedupe_key() not in seen:
            seen.add(issue.dedupe_key())
            merged.append(issue)
    return sort_issues(merged)


@dataclass
class Assessment:
    """Deterministic result of `Analyst.assess`.

    `narrative_facts` is the compact, prompt-ready view of the evidence; None
    means there is nothing worth narrating, so no LLM call is made at all.
    """

    issues: list[Issue]
    score: float
    summary: str
    assessed: bool = True
    narrative_facts: str | None = None
    notes: list[str] = field(default_factory=list)


class Analyst(ABC):
    """One report category: deterministic assessment in code, prompts in markdown.

    The category's prompts live in `agents/instructions/<category>.md` (see
    `agents/prompts.py`), so an analyst's job description is a document a
    reviewer can read, not strings scattered through code.
    """

    category: ClassVar[Category]
    # Tool families the deep investigator gets: files, scanners, dependencies, git_history.
    tool_families: ClassVar[tuple[str, ...]] = ("files",)
    # Penalty that maps to ~37% when re-scoring investigator-added issues.
    rescore_scale: ClassVar[float] = 50.0

    @abstractmethod
    def assess(self, recon: Recon) -> Assessment:
        """Deterministic issues + score from recon data. Must never raise on bad input."""

    @property
    def narrative_prompt(self) -> str:
        """System prompt for the shallow path's single narrative call."""
        return prompts.narrative_prompt(self.category)

    @property
    def investigation_prompt(self) -> str:
        """System prompt for the deep path's tool-calling investigator."""
        return prompts.investigation_prompt(self.category)

    def judge(
        self,
        recon: Recon,
        assessment: Assessment,
        llm: LLMRuntime,
        clone_root: str | None,
    ) -> Assessment:
        """Optional bounded LLM judgment on top of the deterministic assessment.

        Called only when an LLM is available and `ENABLE_LLM_JUDGMENT` is on. It may
        add issues and move the score within a bound the analyst defines; it must
        never remove a deterministic issue. Default: no judgment.
        """
        return assessment

    def score_issues(self, recon: Recon, issues: list[Issue]) -> float | None:
        """The category score for exactly `issues` (used after suppressions remove some).

        None means this category's score isn't a function of its issues (documentation
        scores README metrics), so suppressing an issue hides it but leaves the score.
        """
        return decay_score(issue_penalty(issues), self.rescore_scale)

    def rescore(self, recon: Recon, assessment: Assessment, extra_issues: list[Issue]) -> float:
        """Score after a deep investigation added `extra_issues` (already deduplicated)."""
        return decay_score(issue_penalty(extra_issues), self.rescore_scale, base=assessment.score)

    def unassessed(self, reason: str) -> Assessment:
        return Assessment(issues=[], score=0.0, summary=reason, assessed=False)

    def run_shallow(self, recon: Recon, llm: LLMRuntime | None) -> CategoryFinding:
        """`assess` + `narrate`: the complete shallow path."""
        return self.narrate(self.assess(recon), llm)

    def narrate(self, assessment: Assessment, llm: LLMRuntime | None) -> CategoryFinding:
        """Turn an assessment into a finding, with one LLM-written summary if possible."""
        summary = assessment.summary
        notes = list(assessment.notes)
        if assessment.narrative_facts and llm is not None and llm.available:
            try:
                summary = llm.complete(self.narrative_prompt, assessment.narrative_facts) or summary
            except Exception as e:
                logger.warning(
                    f"{self.category.value}: narrative LLM call failed ({e}); using automated summary"
                )
                notes.append(
                    f"LLM summary unavailable ({type(e).__name__}); automated summary shown."
                )
        return CategoryFinding(
            category=self.category,
            score=assessment.score,
            summary=summary,
            issues=assessment.issues,
            assessed=assessment.assessed,
            investigation_depth=InvestigationDepth.SHALLOW,
            notes=notes,
        )
