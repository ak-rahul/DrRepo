"""Deterministic grounding check for issues reported by an investigator agent.

The shared investigation rules ask agents to report only what they saw with a
tool. This module enforces that mechanically, after the agent finishes and
before its issues are merged into the report:

- A cited file that doesn't exist in the clone, or a line past the end of the
  file, means the claim is fabricated: the issue is **dropped**.
- A real file the agent never opened, listed, searched, or scanned, an
  `evidence` excerpt that isn't in the file, or an issue that cites no file at
  all can't be verified: the issue is **kept, capped at low severity**, and
  marked unverified, so a reviewer can still see it.
- Everything else passes unchanged.

No LLM is involved, so the check is cheap and reproducible.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path

from drrepo.agents.tools import PathEscapesSandboxError, resolve_safe_path
from drrepo.models import Issue, Severity, ToolCallTrace
from drrepo.recon.files import read_text_file

UNVERIFIED_MARK = "[unverified]"
EVIDENCE_WINDOW_LINES = 15  # an excerpt may sit this many lines either side of the cited line
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class GroundingResult:
    kept: list[Issue] = field(default_factory=list)
    downgraded: list[tuple[Issue, str]] = field(default_factory=list)
    dropped: list[tuple[Issue, str]] = field(default_factory=list)

    def note(self) -> str | None:
        """One human-readable line for the category's notes, or None if nothing changed."""
        if not self.downgraded and not self.dropped:
            return None
        parts = []
        if self.dropped:
            parts.append(
                f"dropped {len(self.dropped)} agent finding(s) citing missing files or lines"
            )
        if self.downgraded:
            parts.append(f"marked {len(self.downgraded)} unverified finding(s) as low severity")
        return "Grounding check: " + "; ".join(parts) + "."


def _normalize_path(path: str) -> str:
    """Repo-relative POSIX form; the repository root is "" (so "." and "./" match it)."""
    rel = path.strip().replace("\\", "/").removeprefix("./").strip("/")
    return "" if rel == "." else rel


@dataclass
class Examined:
    """What the agent actually looked at, from its own tool trace."""

    files: set[str] = field(default_factory=set)  # read, scanned, searched, found, or history
    scanned_dirs: set[str] = field(default_factory=set)  # directories a scanner ran over


def examined_paths(trace: list[ToolCallTrace]) -> Examined:
    """Repository-relative paths the agent examined.

    Counted: the `path` argument of read_file, run_scanner_on_path, and
    get_file_git_history, plus any path at the start of a result line
    (search_code's `path:line: ...`, find_files' and scanners' path lists).
    Not counted: merely listing a directory, which shows names, not contents.
    """
    seen = Examined()
    for step in trace:
        path_arg = step.tool_input.get("path")
        if isinstance(path_arg, str) and step.tool != "list_directory":
            rel = _normalize_path(path_arg)
            if step.tool == "run_scanner_on_path":
                seen.scanned_dirs.add(rel)  # "" means the whole repository
            seen.files.add(rel)
        if step.tool == "list_directory":
            continue
        for line in step.observation.splitlines():
            head = line.split(":", 1)[0].strip()
            if head and " " not in head and not head.startswith(("ERROR", "...")):
                seen.files.add(_normalize_path(head))
    return seen


def _covered(path: str, seen: Examined) -> bool:
    """True if `path` was examined directly, or a scanner ran over a directory holding it."""
    if path in seen.files:
        return True
    ancestors = {"", *(str(p).replace("\\", "/") for p in Path(path).parents if str(p) != ".")}
    return bool(ancestors & seen.scanned_dirs)


def _evidence_present(text: str, evidence: str, line: int | None) -> bool:
    needle = _WHITESPACE_RE.sub(" ", evidence).strip()
    if not needle:
        return True
    lines = text.splitlines()
    if line is not None and 1 <= line <= len(lines):
        start = max(0, line - 1 - EVIDENCE_WINDOW_LINES)
        lines = lines[start : line + EVIDENCE_WINDOW_LINES]
    return needle in _WHITESPACE_RE.sub(" ", "\n".join(lines))


def _downgrade(issue: Issue, reason: str) -> Issue:
    return dataclasses.replace(
        issue,
        severity=Severity.LOW if issue.severity.rank < Severity.LOW.rank else issue.severity,
        title=issue.title
        if issue.title.startswith(UNVERIFIED_MARK)
        else f"{UNVERIFIED_MARK} {issue.title}",
        description=f"{issue.description}\n\n(Grounding check: {reason}.)",
    )


def ground_issues(
    issues: list[Issue],
    *,
    clone_root: str,
    trace: list[ToolCallTrace],
    evidence: dict[int, str] | None = None,
) -> GroundingResult:
    """Verify agent `issues` against the clone and the agent's own tool trace.

    `evidence` maps an issue's index to the code excerpt the agent quoted for it.
    """
    root = Path(clone_root)
    seen = examined_paths(trace)
    result = GroundingResult()
    for index, issue in enumerate(issues):
        if not issue.file:
            downgraded = _downgrade(issue, "the finding cites no file")
            result.downgraded.append((downgraded, "no file cited"))
            result.kept.append(downgraded)
            continue

        rel = _normalize_path(issue.file)
        try:
            target = resolve_safe_path(root, rel)
        except PathEscapesSandboxError:
            result.dropped.append((issue, f"path {issue.file!r} is outside the repository"))
            continue
        if not target.is_file():
            result.dropped.append((issue, f"cited file {rel!r} does not exist"))
            continue
        text = read_text_file(target) or ""
        line_count = len(text.splitlines())
        if issue.line is not None and not 1 <= issue.line <= max(line_count, 1):
            result.dropped.append(
                (issue, f"line {issue.line} is outside {rel} ({line_count} lines)")
            )
            continue

        quoted = (evidence or {}).get(index)
        if quoted and not _evidence_present(text, quoted, issue.line):
            reason = f"the quoted evidence was not found in {rel}"
        elif not _covered(rel, seen):
            reason = f"the investigator never opened or searched {rel}"
        else:
            result.kept.append(issue)
            continue
        downgraded = _downgrade(issue, reason)
        result.downgraded.append((downgraded, reason))
        result.kept.append(downgraded)
    return result
