"""Shallow, size- and time-limited clone of a public GitHub repository.

Scope boundary: v2 only supports PUBLIC repositories. Cloning never embeds
credentials in the clone URL (that would leak the token into process
listings), and nothing downstream ever installs, builds, or executes anything
from the clone -- collectors only parse source/manifest text.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import Config
from src.models import CollectorResult, CollectorStatus
from src.utils.logger import logger


@dataclass
class ClonedRepo:
    """A cloned repository on local disk. Caller is responsible for calling `cleanup()`."""

    path: Path
    repo_url: str

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _dir_size_mb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def clone_repo(repo_url: str, config: Config) -> tuple[Optional[ClonedRepo], CollectorResult]:
    """Shallow-clone `repo_url` into a temp directory.

    Returns a `(ClonedRepo | None, CollectorResult)` pair. On failure/oversize,
    the first element is None and the CollectorResult explains why - callers
    should treat that as "downstream collectors that need a clone are skipped",
    not a fatal pipeline error.
    """
    if not repo_url.startswith("https://github.com/"):
        return None, CollectorResult(
            name="repo_clone",
            status=CollectorStatus.ERROR,
            detail="Only https://github.com/<owner>/<repo> URLs are supported",
        )

    dest = Path(tempfile.mkdtemp(prefix="drrepo_clone_"))

    try:
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--no-tags",
                repo_url,
                str(dest),
            ],
            capture_output=True,
            text=True,
            timeout=config.clone_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        logger.warning(f"Clone of {repo_url} timed out after {config.clone_timeout_seconds}s")
        return None, CollectorResult(
            name="repo_clone",
            status=CollectorStatus.ERROR,
            detail=f"Clone timed out after {config.clone_timeout_seconds}s",
        )
    except FileNotFoundError:
        shutil.rmtree(dest, ignore_errors=True)
        return None, CollectorResult(
            name="repo_clone",
            status=CollectorStatus.SKIPPED,
            detail="git executable not found on PATH",
        )

    if result.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        logger.warning(f"Clone of {repo_url} failed: {result.stderr[:300]}")
        return None, CollectorResult(
            name="repo_clone",
            status=CollectorStatus.ERROR,
            detail=f"git clone failed: {result.stderr.strip()[:300]}",
        )

    size_mb = _dir_size_mb(dest)
    if size_mb > config.clone_max_size_mb:
        shutil.rmtree(dest, ignore_errors=True)
        logger.warning(f"Clone of {repo_url} exceeded size cap: {size_mb:.0f}MB")
        return None, CollectorResult(
            name="repo_clone",
            status=CollectorStatus.SKIPPED,
            detail=(
                f"Repository clone is {size_mb:.0f}MB, over the "
                f"{config.clone_max_size_mb}MB analysis limit"
            ),
        )

    cloned = ClonedRepo(path=dest, repo_url=repo_url)
    return cloned, CollectorResult(
        name="repo_clone",
        status=CollectorStatus.OK,
        data={"path": str(dest), "size_mb": round(size_mb, 1)},
    )
