"""Shallow, size- and time-limited clone of a public GitHub repository.

Only public repositories are supported. Credentials are never embedded in the
clone URL, and nothing downstream installs, builds, or executes anything from
the clone -- collectors and tools only read text.

Hardening applied to every clone:
- `GIT_TERMINAL_PROMPT=0` + an empty credential helper: a private or missing
  repo fails immediately instead of hanging on a username prompt (or popping a
  credential-manager dialog on Windows).
- `core.symlinks=false`: symlinks are checked out as plain text files, so no
  file inside the clone can point outside it.
- `GIT_LFS_SKIP_SMUDGE=1`: LFS objects are never downloaded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus, RepoRef

NAME = "repo_clone"


@dataclass
class ClonedRepo:
    """A clone on local disk. The caller must call `cleanup()`."""

    path: Path
    repo_url: str

    def cleanup(self) -> None:
        _rmtree(self.path)


def _rmtree(path: Path) -> None:
    def _on_error(func, p, _exc):
        # Git marks pack files read-only; Windows refuses to delete those.
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_error)
    else:  # pragma: no cover - 3.11 only
        shutil.rmtree(path, onerror=_on_error)


def _dir_size_mb(path: Path) -> float:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GCM_INTERACTIVE": "never",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
    )
    return env


def clone_repo(repo_url: str, config: Config) -> tuple[ClonedRepo | None, CollectorResult]:
    """Shallow-clone `repo_url` into a temp directory.

    Returns `(ClonedRepo | None, CollectorResult)`. On failure the first element
    is None and the result explains why; downstream clone-dependent collectors
    are then skipped rather than failing the whole run.
    """
    try:
        ref = RepoRef.parse(repo_url)
    except ValueError as e:
        return None, CollectorResult(name=NAME, status=CollectorStatus.ERROR, detail=str(e))

    if shutil.which("git") is None:
        return None, CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="git executable not found on PATH"
        )

    dest = Path(tempfile.mkdtemp(prefix="drrepo_clone_"))
    cmd = [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.longpaths=true",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        "--quiet",
        "--",
        ref.clone_url,
        str(dest),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.clone_timeout_seconds,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        _rmtree(dest)
        logger.warning(f"Clone of {ref.full_name} timed out after {config.clone_timeout_seconds}s")
        return None, CollectorResult(
            name=NAME,
            status=CollectorStatus.ERROR,
            detail=f"Clone timed out after {config.clone_timeout_seconds}s",
        )
    except OSError as e:
        _rmtree(dest)
        return None, CollectorResult(
            name=NAME, status=CollectorStatus.ERROR, detail=f"Could not run git: {e}"
        )

    if result.returncode != 0:
        _rmtree(dest)
        stderr = result.stderr.strip()
        logger.warning(f"Clone of {ref.full_name} failed: {stderr[:300]}")
        hint = (
            " (repository is private or does not exist)"
            if "could not read Username" in stderr or "not found" in stderr.lower()
            else ""
        )
        return None, CollectorResult(
            name=NAME,
            status=CollectorStatus.ERROR,
            detail=f"git clone failed{hint}: {stderr[:300]}",
        )

    size_mb = _dir_size_mb(dest)
    if size_mb > config.clone_max_size_mb:
        _rmtree(dest)
        logger.warning(f"Clone of {ref.full_name} exceeded size cap: {size_mb:.0f}MB")
        return None, CollectorResult(
            name=NAME,
            status=CollectorStatus.SKIPPED,
            detail=(
                f"Repository clone is {size_mb:.0f}MB, over the "
                f"{config.clone_max_size_mb}MB analysis limit"
            ),
        )

    logger.info(f"Cloned {ref.full_name} ({size_mb:.1f}MB)")
    return ClonedRepo(path=dest, repo_url=ref.html_url), CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={"size_mb": round(size_mb, 1), "full_name": ref.full_name},
    )
