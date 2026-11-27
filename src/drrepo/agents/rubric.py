"""Documentation rubric: bounded LLM judgment where heuristics are weakest.

README metrics (headings, word counts, links) can't tell a clear README from a
long one, or check that the install command matches the project. A single
structured-output call grades the README against fixed criteria, using the
project's real build config (package name, entry points, lockfiles) as ground
truth. Everything after that call is deterministic:

- verdicts become points in code (met 1, partial 0.5, missing 0; n/a excluded);
- the documentation score moves from the metric score toward the rubric score
  by at most `MAX_ADJUSTMENT` points, so a README that tries to talk the model
  into "perfect" (prompt injection) gains at most that much;
- a "met" verdict that cites a file which doesn't exist in the clone is
  downgraded to "partial" (spot check);
- criteria the model didn't answer are left out, never guessed.

The instructions live in `agents/instructions/documentation.md` under `## Rubric`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from drrepo.agents import prompts
from drrepo.agents.llm import LLMRuntime
from drrepo.agents.tools import PathEscapesSandboxError, resolve_safe_path

CRITERIA: dict[str, str] = {
    "purpose": "states what the project does and who it is for",
    "installation": "gives install instructions consistent with the build config",
    "usage": "shows a usage example consistent with the real entry points",
    "configuration": "documents configuration options or environment variables",
    "contributing": "explains how to set up development, run tests, and contribute",
    "status": "states maintenance status, where to get support, and the license",
}
CriterionName = Literal[
    "purpose", "installation", "usage", "configuration", "contributing", "status"
]
Verdict = Literal["met", "partial", "missing", "not_applicable"]
POINTS = {"met": 1.0, "partial": 0.5, "missing": 0.0}
MAX_ADJUSTMENT = 25.0
MAX_README_CHARS_SENT = 12_000

# Metric issues ("README has no 'X' section") that a "met" verdict shows to be a
# heading-name false positive: content present under another heading.
SECTIONS_BY_CRITERION = {
    "installation": ("Installation",),
    "usage": ("Usage", "Examples"),
    "contributing": ("Contributing",),
    "purpose": ("Features",),
}


# Public names on purpose: Groq rejects tool names starting with "_" (see planner.py).
class RubricItem(BaseModel):
    criterion: CriterionName
    verdict: Verdict
    reason: str = Field(description="One sentence citing what the README does or doesn't say")
    evidence_file: str | None = Field(
        default=None,
        description="Repo-relative file the verdict relies on, if other than the README (e.g. docs/install.md)",
    )


class DocumentationRubricOutput(BaseModel):
    items: list[RubricItem]


@dataclass
class RubricResult:
    items: dict[str, RubricItem]
    rubric_score: float | None
    spot_check_downgrades: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        verdicts = [i.verdict for i in self.items.values()]
        return {v: verdicts.count(v) for v in ("met", "partial", "missing", "not_applicable")}


def bounded_score(metric_score: float, rubric_score: float | None) -> float:
    """The metric score, moved toward the rubric score by at most MAX_ADJUSTMENT."""
    if rubric_score is None:
        return metric_score
    delta = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, rubric_score - metric_score))
    return round(max(0.0, min(100.0, metric_score + delta)), 1)


def rubric_score(items: dict[str, RubricItem]) -> float | None:
    scored = [POINTS[i.verdict] for i in items.values() if i.verdict in POINTS]
    return round(100.0 * sum(scored) / len(scored), 1) if scored else None


def spot_check(items: dict[str, RubricItem], clone_root: str | None) -> list[str]:
    """Downgrade "met" verdicts that rely on a file the clone doesn't have. Mutates `items`."""
    downgraded: list[str] = []
    if clone_root is None:
        return downgraded
    for name, item in items.items():
        if item.verdict != "met" or not item.evidence_file:
            continue
        try:
            exists = resolve_safe_path(Path(clone_root), item.evidence_file).is_file()
        except PathEscapesSandboxError:
            exists = False
        if not exists:
            items[name] = item.model_copy(
                update={
                    "verdict": "partial",
                    "reason": f"{item.reason} (cited {item.evidence_file!r} does not exist)",
                }
            )
            downgraded.append(name)
    return downgraded


def build_input(readme: str, build_config: dict[str, Any], structure: dict[str, Any]) -> str:
    truncated = len(readme) > MAX_README_CHARS_SENT
    criteria = "\n".join(f"- {name}: {text}" for name, text in CRITERIA.items())
    return (
        f"Criteria:\n{criteria}\n\n"
        f"Build configuration (ground truth, parsed from the repository):\n{build_config}\n\n"
        f"Repository files present: { {k: v for k, v in structure.items() if v} }\n\n"
        f"README{' (truncated)' if truncated else ''}:\n"
        f"<<<README\n{readme[:MAX_README_CHARS_SENT]}\nREADME>>>"
    )


def evaluate(
    llm: LLMRuntime,
    readme: str,
    build_config: dict[str, Any],
    structure: dict[str, Any],
    clone_root: str | None,
) -> RubricResult:
    """One structured call, then deterministic scoring. Raises whatever the LLM call raised."""
    output = llm.structured(
        DocumentationRubricOutput,
        prompts.section("documentation", "Rubric"),
        build_input(readme, build_config, structure),
    )
    items: dict[str, RubricItem] = {}
    for item in output.items:
        items.setdefault(item.criterion, item)  # first answer per criterion wins
    downgrades = spot_check(items, clone_root)
    return RubricResult(
        items=items, rubric_score=rubric_score(items), spot_check_downgrades=downgrades
    )
