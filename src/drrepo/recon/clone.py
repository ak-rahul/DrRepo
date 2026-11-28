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
- a requested ref (branch, tag, or commit SHA) is validated against a strict
  pattern before it reaches `git`, and is always passed after `--`.

Every clone records the exact commit it checked out (`commit_sha`), so a report
always says which code it describes. The clone holds one commit, or N+1 with an
opt-in history scan of N commits (`clone_depth`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus, RepoRef

NAME = "repo_clone"

# Branch, tag, or (abbreviated) commit SHA. Deliberately stricter than git's own
# rules: no leading "-", no "..", no "@{", no ".lock" suffix, no whitespace.
_REF_RE = re.compile(r"^(?!.*\.\.)(?!.*@\{)(?!.*\.lock$)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


_ABBREVIATED_SHA_RE = re.compile(r"^[0-9a-f]{7,39}$")


def validate_ref(ref: str) -> str:
    """Return `ref` stripped, or raise ValueError (user-presentable) if it is unsafe."""
    ref = ref.strip()
    if not _REF_RE.match(ref) or ref.endswith("/"):
        raise ValueError(f"{ref!r} is not a valid branch, tag, or commit SHA")
    return ref


@dataclass
class ClonedRepo:
    """A clone on local disk. The caller must call `cleanup()`."""

    path: Path
    repo_url: str

    def cleanup(self) -> None:
        _rmtree(self.path)


def _rmtree(path: Path) -> None:
    def _on_error(func: Callable[[str], object], p: str, _exc: object) -> None:
        # Git marks pack files read-only; Windows refuses to delete those.
        try:
            Path(p).chmod(0o700)
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
                total += (Path(dirpath) / name).lstat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def git_env() -> dict[str, str]:
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


def _git(args: list[str], cwd: Path | None, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "credential.helper=", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=git_env(),
        stdin=subprocess.DEVNULL,
        check=False,  # return codes are inspected by the caller
    )


def clone_depth(config: Config) -> int:
    """Commits to fetch: 1, or N+1 with a history scan of N commits, so the oldest
    scanned commit still has its parent and shows only what it changed."""
    return config.scan_history_commits + 1 if config.scan_history_commits > 0 else 1


def _clone_commands(clone_url: str, dest: Path, ref: str | None, depth: int = 1) -> list[list[str]]:
    """The git invocations for a shallow checkout of the default branch or of `ref`.

    A named ref uses init + fetch instead of `clone --branch`, because only
    fetch accepts a commit SHA (GitHub serves any reachable commit).
    """
    hardening = ["-c", "core.symlinks=false", "-c", "core.longpaths=true"]
    if ref is None:
        return [
            [
                *hardening,
                "clone",
                "--depth",
                str(depth),
                "--single-branch",
                "--no-tags",
                "--quiet",
                "--",
                clone_url,
                str(dest),
            ]
        ]
    return [
        ["init", "--quiet", "--", str(dest)],
        [*hardening, "-C", str(dest), "remote", "add", "origin", "--", clone_url],
        [
            *hardening,
            "-C",
            str(dest),
            "fetch",
            "--depth",
            str(depth),
            "--no-tags",
            "--quiet",
            "origin",
            "--",
            ref,
        ],
        [*hardening, "-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
    ]


def clone_repo(
    repo_url: str, config: Config, ref: str | None = None
) -> tuple[ClonedRepo | None, CollectorResult]:
    """Shallow-clone `repo_url` (at `ref`, or the default branch) into a temp directory.

    Returns `(ClonedRepo | None, CollectorResult)`. On failure the first element
    is None and the result explains why; downstream clone-dependent collectors
    are then skipped rather than failing the whole run. On success the result's
    data holds `commit_sha` (full SHA of the checked-out commit) and `ref`.
    """
    try:
        repo = RepoRef.parse(repo_url)
        if ref is not None:
            ref = validate_ref(ref)
    except ValueError as e:
        return None, CollectorResult(name=NAME, status=CollectorStatus.ERROR, detail=str(e))

    if shutil.which("git") is None:
        return None, CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="git executable not found on PATH"
        )

    dest = Path(tempfile.mkdtemp(prefix="drrepo_clone_"))
    target = f"{repo.full_name}@{ref}" if ref else repo.full_name
    for args in _clone_commands(repo.clone_url, dest, ref, clone_depth(config)):
        try:
            result = _git(args, cwd=None, timeout=config.clone_timeout_seconds)
        except subprocess.TimeoutExpired:
            _rmtree(dest)
            logger.warning(f"Clone of {target} timed out after {config.clone_timeout_seconds}s")
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
            logger.warning(f"Clone of {target} failed: {stderr[:300]}")
            if "could not read Username" in stderr or "not found" in stderr.lower():
                hint = " (repository is private or does not exist)"
            elif ref and ("couldn't find remote ref" in stderr or "not our ref" in stderr):
                hint = (
                    " (abbreviated SHAs can't be fetched; use the full 40-character SHA)"
                    if _ABBREVIATED_SHA_RE.match(ref)
                    else f" (no branch, tag, or commit named {ref!r})"
                )
            else:
                hint = ""
            return None, CollectorResult(
                name=NAME,
                status=CollectorStatus.ERROR,
                detail=f"git clone failed{hint}: {stderr[:300]}",
            )

    head = _git(["-C", str(dest), "rev-parse", "HEAD"], cwd=None, timeout=30)
    commit_sha = head.stdout.strip() if head.returncode == 0 else None

    size_mb = _dir_size_mb(dest)
    if size_mb > config.clone_max_size_mb:
        _rmtree(dest)
        logger.warning(f"Clone of {target} exceeded size cap: {size_mb:.0f}MB")
        return None, CollectorResult(
            name=NAME,
            status=CollectorStatus.SKIPPED,
            detail=(
                f"Repository clone is {size_mb:.0f}MB, over the "
                f"{config.clone_max_size_mb}MB analysis limit"
            ),
        )

    logger.info(f"Cloned {target} at {(commit_sha or '?')[:12]} ({size_mb:.1f}MB)")
    return ClonedRepo(path=dest, repo_url=repo.html_url), CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={
            "size_mb": round(size_mb, 1),
            "full_name": repo.full_name,
            "commit_sha": commit_sha,
            "ref": ref,
        },
    )
