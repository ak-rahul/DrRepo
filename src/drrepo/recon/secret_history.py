"""Opt-in secret scan over recent git history (`--scan-history N`).

A secret deleted from the code is still readable in git history. With
`SCAN_HISTORY_COMMITS=N`, the clone fetches N+1 commits (`clone.clone_depth`)
and this collector reads the lines the newest N commits added, from
`git log -p`, a read-only git command. Nothing is checked out or run:
`--no-ext-diff` and `--no-textconv` keep git from invoking any diff driver.

The same patterns as the tree scanner apply (`secrets.match_secret`). A secret
still present in the current tree is left to that scanner, so each finding here
is one that only history holds. Each finding names the commit that added it. The
output read is capped in bytes and time; a capped scan says so in `truncated`.

`data` schema (status OK):
    commits_scanned: int, truncated: bool,
    findings: [{tool: "secret_history", rule, severity, file, line, commit, date, message}]
"""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.clone import git_env
from drrepo.recon.secrets import is_fixture_path, is_scannable, match_secret, secret_severity

NAME = "secret_history"
MAX_COMMITS = 1000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_COMMIT_MARK = "\x00"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# A history severity is one level below the tree's: the secret was removed, and
# may have been rotated, but it stays readable by anyone with the repository.
_HISTORY_SEVERITY = {"CRITICAL": "HIGH", "HIGH": "MEDIUM", "LOW": "LOW"}


def git_log_command(root: Path, commits: int) -> list[str]:
    return [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.quotepath=off",
        "-C",
        str(root),
        "log",
        "-p",
        "-U0",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--diff-merges=off",
        "--format=%x00%H %cI",  # git prints %x00 as the NUL _COMMIT_MARK
        "-n",
        str(commits),
        "HEAD",
        "--",
    ]


def added_secrets(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Secrets on added lines of a `git log -p -U0` stream, newest commit first."""
    commit = date = path = None
    line_no = 0
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith(_COMMIT_MARK):
            commit, _, date = line[1:].partition(" ")
            path = None
        elif line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None  # /dev/null: a deletion
        elif line.startswith("@@"):
            hunk = _HUNK.match(line)
            line_no = int(hunk.group(1)) if hunk else 0
        elif line.startswith("+") and path and commit:
            rule = match_secret(line[1:])
            if rule and is_scannable(path):
                yield {"rule": rule, "file": path, "line": line_no, "commit": commit, "date": date}
            line_no += 1


def _stream(process: subprocess.Popen[str], cap: int, commits: list[str]) -> Iterator[str]:
    """`process` output line by line, up to `cap` characters; records each commit read."""
    read = 0
    for line in process.stdout or ():
        read += len(line)
        if read > cap:
            raise OverflowError
        if line.startswith(_COMMIT_MARK):
            commits.append(line[1:41])
        yield line


def scan_history(
    root: Path, commits: int, *, present: set[tuple[str, str]], timeout: float
) -> dict[str, Any]:
    """Secrets added in the last `commits` commits that the tree no longer has."""
    process = subprocess.Popen(
        git_log_command(root, commits),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_env(),
    )
    timed_out = threading.Event()

    def stop() -> None:
        timed_out.set()
        process.kill()

    timer = threading.Timer(timeout, stop)
    timer.start()
    oldest: dict[tuple[str, str], dict[str, Any]] = {}
    read_commits: list[str] = []
    truncated = False
    try:
        for found in added_secrets(_stream(process, MAX_OUTPUT_BYTES, read_commits)):
            key = (found["file"], found["rule"])
            if key not in present:
                oldest[key] = found  # the log is newest first: keep the commit that added it
    except OverflowError:
        truncated = True
    finally:
        process.kill()
        process.wait()
        timer.cancel()
    truncated = truncated or timed_out.is_set()
    findings = []
    for (path, rule), found in sorted(oldest.items()):
        severity = _HISTORY_SEVERITY[secret_severity(rule, path)]
        findings.append(
            {
                "tool": NAME,
                "rule": rule,
                "severity": severity,
                "file": path,
                "line": found["line"],
                "commit": found["commit"],
                "date": found["date"],
                "message": (
                    f"Possible {rule} added to {path} in commit {found['commit'][:12]} "
                    f"({(found['date'] or '')[:10]}) and no longer in the current tree"
                    + ("; it is in a test/fixture path" if is_fixture_path(path) else "")
                ),
            }
        )
    return {"commits_scanned": len(read_commits), "truncated": truncated, "findings": findings}


def collect_secret_history(
    clone_path: str, config: Config, present: set[tuple[str, str]]
) -> CollectorResult:
    """`present`: `(file, rule)` pairs the tree scanner already reported."""
    commits = min(config.scan_history_commits, MAX_COMMITS)
    if commits <= 0:
        return CollectorResult.skipped(NAME, "Off (opt in with --scan-history N)")
    root = Path(clone_path)
    if not (root / ".git").exists():
        return CollectorResult.skipped(NAME, "No local clone available")
    try:
        data = scan_history(
            root, commits, present=present, timeout=float(config.collector_timeout_seconds)
        )
    except OSError as e:
        logger.warning(f"git log failed: {e}")
        return CollectorResult(
            name=NAME, status=CollectorStatus.ERROR, detail=f"git log failed: {e}"
        )
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data=data,
        detail="Output cap or time limit reached; older commits were not read"
        if data["truncated"]
        else None,
    )
