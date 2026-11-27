"""Filesystem helpers shared by collectors and investigator tools.

Every walk over a clone goes through `iter_repo_files`, so the skip rules
(vendored/build directories, symlinks, oversized or binary files) are defined
exactly once. Skip checks look at path parts *relative to the clone root* --
checking the absolute path would wrongly skip everything if the temp directory
itself happened to live under a folder named e.g. `build`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "target",
        "vendor",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        "coverage",
    }
)
DEFAULT_MAX_FILE_BYTES = 512_000


def relative_posix(path: str | Path, root: str | Path) -> str:
    """`path` relative to `root`, with forward slashes; unchanged if not under root.

    Scanners emit absolute paths (ruff) or `./`-prefixed ones (bandit). Reports,
    SARIF, and the LLM must all see stable repo-relative paths instead of a
    temp directory that no longer exists after the run.
    """
    p = Path(path)
    root_path = Path(root).resolve()
    if not p.is_absolute():
        p = root_path / p
    try:
        return p.resolve().relative_to(root_path).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def is_skipped(rel_parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIRS for part in rel_parts[:-1])


def iter_repo_files(
    root: str | Path, max_bytes: int | None = DEFAULT_MAX_FILE_BYTES
) -> Iterator[Path]:
    """Yield regular files under `root`, pruning skipped dirs and never following symlinks."""
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if max_bytes is not None and path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            yield path


def read_text_file(path: Path) -> str | None:
    """Read a file as UTF-8 text, or return None if it looks binary/unreadable."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="ignore")
