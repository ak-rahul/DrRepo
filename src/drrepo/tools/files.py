"""Read-only file tools: `read_file`, `list_directory`, `search_code`, `find_files`.

Every path is resolved relative to the clone root and must stay inside it.
This guard is load-bearing: the LLM picks these arguments. Symlinks were
already neutralized at clone time (`core.symlinks=false`), and resolution
follows any that remain, so an escape via symlink is rejected too.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from drrepo.collectors.filesystem import SKIP_DIRS, iter_repo_files, read_text_file, relative_posix

MAX_READ_CHARS = 40_000
MAX_READ_FILE_BYTES = 2_000_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_MATCHES = 80
MAX_PATTERN_LENGTH = 300


class PathEscapesSandboxError(ValueError):
    """A requested path would resolve outside the clone root (or is malformed)."""


def resolve_safe_path(root: Path, requested: str) -> Path:
    """Resolve `requested` under `root`, rejecting anything that escapes it."""
    root = root.resolve()
    if "\x00" in requested:
        raise PathEscapesSandboxError(f"Path {requested!r} is invalid (NUL byte)")
    try:
        candidate = (root / requested.strip()).resolve()
    except (ValueError, OSError) as e:
        raise PathEscapesSandboxError(f"Path {requested!r} is invalid: {e}") from e
    if candidate != root and root not in candidate.parents:
        raise PathEscapesSandboxError(f"Path {requested!r} escapes the repository root")
    return candidate


def _safe_glob(glob: str | None) -> str | None:
    if glob is None:
        return None
    glob = glob.strip()
    if (
        not glob
        or ".." in glob.replace("\\", "/").split("/")
        or glob.startswith(("/", "\\"))
        or ":" in glob
    ):
        raise PathEscapesSandboxError(
            f"Glob {glob!r} must be a relative pattern like '*.py' or 'src/**/*.ts'"
        )
    return glob


def _matches(rel: str, glob: str) -> bool:
    return fnmatch.fnmatch(rel, glob) or (
        "/" not in glob and fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob)
    )


def make_file_tools(clone_root: str) -> list[Any]:
    root = Path(clone_root).resolve()

    @tool
    def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Read a text file from the repository, optionally a 1-indexed inclusive line range.

        Args:
            path: File path relative to the repository root, e.g. "src/app/main.py".
            start_line: First line to include (optional).
            end_line: Last line to include (optional).
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.is_file():
            return f"ERROR: '{path}' is not a file (use list_directory or find_files)"
        try:
            size = target.stat().st_size
        except OSError as e:
            return f"ERROR: could not stat '{path}': {e}"
        if size > MAX_READ_FILE_BYTES:
            return f"ERROR: '{path}' is {size:,} bytes, too large; use search_code instead"
        text = read_text_file(target)
        if text is None:
            return f"ERROR: '{path}' looks like a binary file"

        lines = text.splitlines()
        if start_line or end_line:
            start = max((start_line or 1) - 1, 0)
            end = min(end_line or len(lines), len(lines))
            selected = lines[start:end]
            first = start + 1
        else:
            selected, first = lines, 1
        body = "\n".join(f"{n:>5}| {line}" for n, line in enumerate(selected, start=first))
        if len(body) > MAX_READ_CHARS:
            body = (
                body[:MAX_READ_CHARS]
                + f"\n... [truncated; file has {len(lines)} lines, use start_line/end_line]"
            )
        return body or "(empty file)"

    @tool
    def list_directory(path: str = ".") -> str:
        """List files and subdirectories at a path in the repository.

        Args:
            path: Directory relative to the repository root; "." is the root.
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.is_dir():
            return f"ERROR: '{path}' is not a directory"
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for entry in entries[:MAX_LIST_ENTRIES]:
            rel = relative_posix(entry, root)
            if entry.is_dir():
                lines.append(
                    f"dir   {rel}/"
                    + ("  (vendored/build, skipped by search)" if entry.name in SKIP_DIRS else "")
                )
            else:
                try:
                    lines.append(f"file  {rel}  ({entry.stat().st_size:,} bytes)")
                except OSError:
                    lines.append(f"file  {rel}")
        if len(entries) > MAX_LIST_ENTRIES:
            lines.append(f"... and {len(entries) - MAX_LIST_ENTRIES} more entries")
        return "\n".join(lines) or "(empty directory)"

    @tool
    def find_files(glob: str) -> str:
        """Find files by path pattern, e.g. "*.py", "**/test_*.py", ".github/workflows/*".

        Args:
            glob: fnmatch-style pattern matched against repo-relative paths (and bare filenames).
        """
        try:
            pattern = _safe_glob(glob)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if pattern is None:
            return "ERROR: a glob pattern is required"
        matches = []
        for path in iter_repo_files(root, max_bytes=None):
            rel = relative_posix(path, root)
            if _matches(rel, pattern):
                matches.append(rel)
                if len(matches) >= MAX_LIST_ENTRIES:
                    matches.append("... [truncated]")
                    break
        return "\n".join(matches) or "No files matched"

    @tool
    def search_code(pattern: str, glob: str | None = None, ignore_case: bool = False) -> str:
        """Search repository file contents for a Python regular expression.

        Args:
            pattern: Regular expression, e.g. "subprocess\\.(run|Popen)".
            glob: Optional path pattern to restrict the search, e.g. "*.py".
            ignore_case: Case-insensitive match.
        """
        if len(pattern) > MAX_PATTERN_LENGTH:
            return f"ERROR: pattern longer than {MAX_PATTERN_LENGTH} characters"
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
            file_glob = _safe_glob(glob)
        except re.error as e:
            return f"ERROR: invalid regex: {e}"
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"

        matches: list[str] = []
        for path in iter_repo_files(root):
            rel = relative_posix(path, root)
            if file_glob and not _matches(rel, file_glob):
                continue
            text = read_text_file(path)
            if text is None:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if len(line) <= 2000 and regex.search(line):
                    matches.append(f"{rel}:{line_no}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        return "\n".join(matches) + "\n... [truncated: narrow the pattern or glob]"
        return "\n".join(matches) or "No matches found"

    return [read_file, list_directory, find_files, search_code]
