"""Read-only file inspection tools for investigator agents.

Every path is resolved relative to the clone root and asserted to stay
inside it before touching disk. This guard is the load-bearing safety
mechanism in v3: an LLM chooses the path argument itself, unlike v2's
collectors which never accepted an LLM-controlled path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import tool

_MAX_READ_CHARS = 50_000
_MAX_FILE_BYTES_TO_SCAN = 512_000
_MAX_LIST_ENTRIES = 200
_MAX_SEARCH_MATCHES = 100
_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}


class PathEscapesSandboxError(ValueError):
    """Raised when a requested path would resolve outside the clone root."""


def resolve_safe_path(root: Path, requested: str) -> Path:
    """Resolve `requested` relative to `root`, rejecting any path that escapes it."""
    root = root.resolve()
    candidate = (root / requested).resolve()
    if candidate != root and root not in candidate.parents:
        raise PathEscapesSandboxError(f"Path '{requested}' escapes the repository root")
    return candidate


def make_file_tools(clone_root: str) -> List:
    """Build `read_file`/`list_directory`/`search_code` tools bound to a clone root.

    Returns a list of LangChain tool objects ready to pass to an agent.
    """
    root = Path(clone_root)

    @tool
    def read_file(
        path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
    ) -> str:
        """Read a text file from the repository. Optionally restrict to a line range.

        Args:
            path: File path relative to the repository root, e.g. "src/main.py".
            start_line: 1-indexed first line to include (optional).
            end_line: 1-indexed last line to include (optional).
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"

        if not target.is_file():
            return f"ERROR: '{path}' is not a file"

        try:
            text = target.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            return f"ERROR: could not read '{path}': {e}"

        if start_line or end_line:
            lines = text.splitlines()
            start = max((start_line or 1) - 1, 0)
            end = end_line or len(lines)
            text = "\n".join(lines[start:end])

        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n... [truncated]"
        return text or "(empty file)"

    @tool
    def list_directory(path: str = ".") -> str:
        """List files and directories at the given path within the repository.

        Args:
            path: Directory path relative to the repository root. Use "." for the root.
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"

        if not target.is_dir():
            return f"ERROR: '{path}' is not a directory"

        entries = sorted(target.iterdir())[:_MAX_LIST_ENTRIES]
        lines = [
            f"{'dir' if entry.is_dir() else 'file'}\t{entry.relative_to(root)}" for entry in entries
        ]
        return "\n".join(lines) if lines else "(empty directory)"

    @tool
    def search_code(pattern: str, glob: Optional[str] = None) -> str:
        """Search file contents in the repository for a regex pattern.

        Args:
            pattern: Python regular expression to search for.
            glob: Optional filename glob to restrict the search, e.g. "*.py".
        """
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"ERROR: invalid regex: {e}"

        matches = []
        file_iter = root.rglob(glob) if glob else root.rglob("*")
        for file in file_iter:
            if not file.is_file() or any(part in _SKIP_DIRS for part in file.parts):
                continue
            try:
                if file.stat().st_size > _MAX_FILE_BYTES_TO_SCAN:
                    continue
                text = file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{file.relative_to(root)}:{line_no}: {line.strip()[:200]}")
                    if len(matches) >= _MAX_SEARCH_MATCHES:
                        return "\n".join(matches) + "\n... [truncated, too many matches]"

        return "\n".join(matches) if matches else "No matches found"

    return [read_file, list_directory, search_code]
