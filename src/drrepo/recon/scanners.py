"""Static-analysis scanners and the two collectors built on them.

- `collect_static_analysis`: ruff (bug-class rules) -> code quality.
- `collect_security`: bandit + semgrep `p/security-audit` + the secret scanner.

The same `run_*` wrappers back the investigator's `run_scanner_on_path` tool,
so a deep dive sees exactly what the recon pass saw. Every wrapper:
- runs with `cwd` set to the clone root and never executes repository code
  (all three tools only parse source);
- returns a `ScanResult` whose findings use repo-relative POSIX paths;
- reports `available=False` with a reason instead of raising, so a missing
  binary or a timeout degrades one signal rather than the run.

Finding shape: {"tool", "rule", "message", "severity", "file", "line", "url"?}
Both collectors' data schema (status OK): findings: [finding], tool_status: {tool: str}
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.files import SKIP_DIRS, relative_posix
from drrepo.recon.secrets import scan_secrets

# Ruff runs `--isolated` (ignoring the analyzed repo's own config, which could
# simply disable every rule) with a fixed, bug-focused rule set so scores are
# comparable across repositories.
RUFF_RULES = "E4,E7,E9,F,B,PLE"
SEMGREP_CONFIG = "p/security-audit"
TEST_DIRS = frozenset({"tests", "test", "testing"})
_BANDIT_EXCLUDES = ",".join(f"*/{d}/*" for d in sorted(SKIP_DIRS | TEST_DIRS))


@dataclass
class ScanResult:
    tool: str
    available: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None


def find_executable(name: str) -> str | None:
    """Prefer the tool installed next to the running interpreter (the project's
    venv), falling back to PATH."""
    scripts_dir = Path(sys.executable).parent
    for candidate in (scripts_dir / name, scripts_dir / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _run(tool: str, args: list[str], cwd: Path, timeout: int) -> tuple[str | None, str | None]:
    """Run a scanner; return (stdout, error_reason)."""
    exe = find_executable(tool)
    if exe is None:
        return None, f"{tool} not installed"
    try:
        proc = subprocess.run(
            [exe, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None, f"{tool} timed out after {timeout}s"
    except OSError as e:
        return None, f"{tool} could not run: {e}"
    return proc.stdout, None


def _target_arg(root: Path, target: Path) -> str:
    rel = relative_posix(target, root)
    return "." if rel in ("", ".") else rel


def run_ruff(root: Path, target: Path | None = None, timeout: int = 120) -> ScanResult:
    target_arg = _target_arg(root, target or root)
    stdout, err = _run(
        "ruff",
        [
            "check",
            target_arg,
            "--isolated",
            f"--select={RUFF_RULES}",
            "--output-format=json",
            "--exit-zero",
            "--no-cache",
            "--force-exclude",
            # Tests are excluded so findings match the source-only line count the
            # code-quality score is normalized by (see collectors/layout.py).
            f"--extend-exclude={','.join(sorted(SKIP_DIRS | TEST_DIRS))}",
        ],
        root,
        timeout,
    )
    if err:
        return ScanResult("ruff", False, reason=err)
    try:
        items = json.loads(stdout or "[]")
    except json.JSONDecodeError as e:
        return ScanResult("ruff", False, reason=f"unparseable ruff output: {e}")
    findings = [
        {
            "tool": "ruff",
            "rule": item.get("code") or "syntax-error",
            "message": item.get("message") or "",
            "severity": None,
            "file": relative_posix(item.get("filename", ""), root),
            "line": (item.get("location") or {}).get("row"),
            "url": item.get("url"),
        }
        for item in items
    ]
    return ScanResult("ruff", True, findings)


def run_bandit(root: Path, target: Path | None = None, timeout: int = 120) -> ScanResult:
    target_arg = _target_arg(root, target or root)
    args = ["-f", "json", "-q", "--skip", "B101", "-x", _BANDIT_EXCLUDES]
    args += ["-r", target_arg] if (target or root).is_dir() else [target_arg]
    stdout, err = _run("bandit", args, root, timeout)
    if err:
        return ScanResult("bandit", False, reason=err)
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as e:
        return ScanResult("bandit", False, reason=f"unparseable bandit output: {e}")
    findings = [
        {
            "tool": "bandit",
            "rule": item.get("test_id"),
            "message": item.get("issue_text") or "",
            "severity": item.get("issue_severity"),
            "confidence": item.get("issue_confidence"),
            "file": relative_posix(item.get("filename", ""), root),
            "line": item.get("line_number"),
            "url": item.get("more_info"),
        }
        for item in payload.get("results", [])
    ]
    return ScanResult("bandit", True, findings)


def run_semgrep(root: Path, target: Path | None = None, timeout: int = 120) -> ScanResult:
    target_arg = _target_arg(root, target or root)
    stdout, err = _run(
        "semgrep",
        [
            "scan",
            f"--config={SEMGREP_CONFIG}",
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            f"--timeout={max(5, timeout // 4)}",
            target_arg,
        ],
        root,
        timeout,
    )
    if err:
        return ScanResult("semgrep", False, reason=err)
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as e:
        return ScanResult("semgrep", False, reason=f"unparseable semgrep output: {e}")
    findings = [
        {
            "tool": "semgrep",
            "rule": item.get("check_id"),
            "message": (item.get("extra") or {}).get("message") or "",
            "severity": (item.get("extra") or {}).get("severity"),
            "file": relative_posix(item.get("path", ""), root),
            "line": (item.get("start") or {}).get("line"),
        }
        for item in payload.get("results", [])
    ]
    return ScanResult("semgrep", True, findings)


SCANNERS = {"ruff": run_ruff, "bandit": run_bandit, "semgrep": run_semgrep}

# ---------------------------------------------------------- collectors ---


def collect_static_analysis(clone_path: str, config: Config) -> CollectorResult:
    """ruff over the clone (tests excluded, matching the code-size denominator)."""
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult.skipped("static_analysis", "No local clone available")
    ruff = run_ruff(root, timeout=config.collector_timeout_seconds)
    if not ruff.available:
        logger.info(f"ruff skipped: {ruff.reason}")
        return CollectorResult(
            name="static_analysis",
            status=CollectorStatus.SKIPPED,
            data={"tool_status": {"ruff": f"skipped: {ruff.reason}"}},
            detail=f"ruff unavailable: {ruff.reason}",
        )
    return CollectorResult(
        name="static_analysis",
        status=CollectorStatus.OK,
        data={"findings": ruff.findings, "tool_status": {"ruff": "ok"}},
    )


def collect_security(clone_path: str, config: Config) -> CollectorResult:
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult(
            name="security", status=CollectorStatus.SKIPPED, detail="No local clone available"
        )

    timeout = config.collector_timeout_seconds
    tool_status: dict[str, str] = {}
    findings: list[dict[str, Any]] = []

    for enabled, tool, runner in (
        (config.enable_bandit, "bandit", run_bandit),
        (config.enable_semgrep, "semgrep", run_semgrep),
    ):
        if not enabled:
            tool_status[tool] = "disabled by config"
            continue
        result = runner(root, timeout=timeout)
        if result.available:
            tool_status[tool] = "ok"
            findings.extend(result.findings)
        else:
            tool_status[tool] = f"skipped: {result.reason}"
            logger.info(f"{tool} skipped: {result.reason}")

    try:
        findings.extend(scan_secrets(root))
        tool_status["secret_scan"] = "ok"
    except Exception as e:  # the scanner must never take the collector down
        tool_status["secret_scan"] = f"error: {e}"
        logger.error(f"Secret scan failed: {e}")

    if not any(v == "ok" for v in tool_status.values()):
        return CollectorResult(
            name="security",
            status=CollectorStatus.SKIPPED,
            data={"tool_status": tool_status},
            detail="No security scanners were available",
        )
    return CollectorResult(
        name="security",
        status=CollectorStatus.OK,
        data={"findings": findings, "tool_status": tool_status},
    )
