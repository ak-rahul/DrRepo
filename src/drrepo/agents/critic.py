"""Critic pass: a second, independent look at severe agent findings.

A high or critical finding from an investigator moves scores and wakes people
up, so before it is merged each one goes to a critic: one structured-output
call, no tools, that sees only the claim and the cited code. The critic answers
`confirmed`, `downgrade` or `reject` per finding, and code applies the verdicts
within fixed bounds:

- `confirmed` leaves the finding as it is;
- `downgrade` lowers it one severity level;
- `reject` lowers it to low and marks it `[disputed]`, keeping it visible.

The critic can never raise a severity or remove a finding, and a failed call
changes nothing, so the worst a prompt injection in the analyzed code can do
is turn an agent finding into a visible "disputed" one. Deterministic scanner
findings are never sent: only agent findings that already passed grounding.

The instructions live in `agents/instructions/critic.md`; the critic has its
own model role (`MODEL_NAME_CRITIC`) and budget line (`critic`).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from drrepo.agents import prompts
from drrepo.agents.grounding import UNVERIFIED_MARK
from drrepo.agents.llm import LLMRuntime
from drrepo.agents.tools import PathEscapesSandboxError, resolve_safe_path
from drrepo.log import logger
from drrepo.models import Issue, Severity
from drrepo.recon.files import read_text_file

DISPUTED_MARK = "[disputed]"
SEVERE = (Severity.CRITICAL, Severity.HIGH)
MAX_FINDINGS_PER_CATEGORY = 6
SNIPPET_CONTEXT_LINES = 12  # either side of the cited line
SNIPPET_HEAD_LINES = 40  # when no line is cited
MAX_SNIPPET_CHARS = 3000
ONE_LEVEL_LOWER = {
    Severity.CRITICAL: Severity.HIGH,
    Severity.HIGH: Severity.MEDIUM,
    Severity.MEDIUM: Severity.LOW,
    Severity.LOW: Severity.LOW,
}


# Public names on purpose: Groq rejects tool names starting with "_" (see planner.py).
class CriticVerdictOutput(BaseModel):
    finding: int = Field(description="The finding's number, as given")
    verdict: Literal["confirmed", "downgrade", "reject"]
    reason: str = Field(description="One sentence citing the code")


class CriticReviewOutput(BaseModel):
    verdicts: list[CriticVerdictOutput]


@dataclass
class CriticResult:
    issues: list[Issue]
    reviewed: int = 0
    confirmed: int = 0
    downgraded: list[tuple[str, str]] = field(default_factory=list)  # (title, reason)
    disputed: list[tuple[str, str]] = field(default_factory=list)
    unanswered: int = 0
    not_reviewed: int = 0  # past MAX_FINDINGS_PER_CATEGORY
    error: str | None = None

    def note(self) -> str | None:
        """One line for the category's notes, or None when there was nothing to review."""
        if self.error:
            return f"Critic unavailable ({self.error}); severe agent findings were not re-checked."
        if not self.reviewed:
            return None
        parts = [f"Critic reviewed {self.reviewed} severe agent finding(s)"]
        outcome = [f"{self.confirmed} confirmed"]
        if self.downgraded:
            outcome.append(f"{len(self.downgraded)} downgraded")
        if self.disputed:
            outcome.append(f"{len(self.disputed)} disputed")
        if self.unanswered:
            outcome.append(f"{self.unanswered} unanswered (left as reported)")
        text = f"{parts[0]}: {', '.join(outcome)}"
        if self.not_reviewed:
            text += (
                f"; {self.not_reviewed} more were not reviewed (limit {MAX_FINDINGS_PER_CATEGORY})"
            )
        return text + "."


def candidates(issues: list[Issue]) -> list[int]:
    """Indexes of the findings the critic reviews: severe, from an agent, grounded."""
    return [
        index
        for index, issue in enumerate(issues)
        if issue.severity in SEVERE
        and issue.source.startswith("investigator:")
        and not issue.title.startswith(UNVERIFIED_MARK)
    ]


def snippet(clone_root: str, issue: Issue) -> str:
    """The cited code with line numbers, or a note when it can't be read."""
    if not issue.file:
        return "(no file cited)"
    try:
        path = resolve_safe_path(Path(clone_root), issue.file)
    except PathEscapesSandboxError:
        return "(cited path is outside the repository)"
    lines = (read_text_file(path) or "").splitlines()
    if not lines:
        return "(cited file is empty or unreadable)"
    if issue.line and 1 <= issue.line <= len(lines):
        start = max(1, issue.line - SNIPPET_CONTEXT_LINES)
        end = min(len(lines), issue.line + SNIPPET_CONTEXT_LINES)
    else:
        start, end = 1, min(len(lines), SNIPPET_HEAD_LINES)
    marked = issue.line or -1
    text = "\n".join(
        f"{'>' if n == marked else ' '}{n:5d}  {lines[n - 1]}" for n in range(start, end + 1)
    )
    return text[:MAX_SNIPPET_CHARS]


def build_input(issues: list[Issue], indexes: list[int], clone_root: str) -> str:
    blocks = []
    for number, index in enumerate(indexes, start=1):
        issue = issues[index]
        where = f"{issue.file}:{issue.line}" if issue.line else str(issue.file)
        blocks.append(
            f"Finding {number} [{issue.severity.value}] {issue.title}\n"
            f"Claim: {issue.description}\n"
            f"Cited: {where}\n"
            f"<<<CODE\n{snippet(clone_root, issue)}\nCODE>>>"
        )
    return "\n\n".join(blocks)


def _annotate(issue: Issue, severity: Severity, reason: str, *, disputed: bool) -> Issue:
    title = issue.title
    if disputed and not title.startswith(DISPUTED_MARK):
        title = f"{DISPUTED_MARK} {title}"
    return dataclasses.replace(
        issue,
        severity=severity,
        title=title,
        description=f"{issue.description}\n\n(Critic: {reason})",
    )


def review(llm: LLMRuntime, issues: list[Issue], clone_root: str) -> CriticResult:
    """Apply the critic to `issues` (an agent's grounded findings). Never raises."""
    indexes = candidates(issues)
    if not indexes:
        return CriticResult(issues=list(issues))
    reviewed, skipped = (
        indexes[:MAX_FINDINGS_PER_CATEGORY],
        indexes[MAX_FINDINGS_PER_CATEGORY:],
    )
    try:
        output = llm.structured(
            CriticReviewOutput,
            prompts.section("critic", "System"),
            build_input(issues, reviewed, clone_root),
        )
    except Exception as e:
        logger.warning(f"Critic call failed, keeping findings as reported: {e}")
        return CriticResult(issues=list(issues), error=type(e).__name__)

    verdicts: dict[int, CriticVerdictOutput] = {}
    for verdict in output.verdicts:
        if 1 <= verdict.finding <= len(reviewed):
            verdicts.setdefault(verdict.finding, verdict)  # first answer per finding wins

    result = CriticResult(issues=list(issues), reviewed=len(reviewed), not_reviewed=len(skipped))
    for number, index in enumerate(reviewed, start=1):
        issue = issues[index]
        answer = verdicts.get(number)
        if answer is None:
            result.unanswered += 1
        elif answer.verdict == "confirmed":
            result.confirmed += 1
        elif answer.verdict == "downgrade":
            lowered = ONE_LEVEL_LOWER[issue.severity]
            result.issues[index] = _annotate(issue, lowered, answer.reason, disputed=False)
            result.downgraded.append((issue.title, answer.reason))
        else:
            result.issues[index] = _annotate(issue, Severity.LOW, answer.reason, disputed=True)
            result.disputed.append((issue.title, answer.reason))
    return result
