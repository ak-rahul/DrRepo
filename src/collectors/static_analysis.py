"""Code-quality static analysis: ruff (Python) + semgrep (multi-language).

Both tools only parse source ASTs -- neither executes, installs, or builds
the analyzed repository. If a tool binary isn't on PATH, the collector
reports SKIPPED with a reason instead of failing the whole pipeline.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from src.config import Config
from src.models import CollectorResult, CollectorStatus
from src.utils.logger import logger

_SEMGREP_CONFIG = "p/security-audit"


def _run_ruff(repo_path: Path, timeout: int) -> Dict[str, Any]:
    if shutil.which("ruff") is None:
        return {"available": False, "reason": "ruff not installed"}

    try:
        result = subprocess.run(
            ["ruff", "check", str(repo_path), "--output-format=json", "--exit-zero"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        findings = json.loads(result.stdout or "[]")
        return {"available": True, "findings": findings}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "ruff timed out"}
    except (json.JSONDecodeError, OSError) as e:
        return {"available": False, "reason": f"ruff error: {e}"}


def _run_semgrep(repo_path: Path, timeout: int) -> Dict[str, Any]:
    if shutil.which("semgrep") is None:
        return {"available": False, "reason": "semgrep not installed"}

    try:
        result = subprocess.run(
            [
                "semgrep",
                "scan",
                f"--config={_SEMGREP_CONFIG}",
                str(repo_path),
                "--json",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        payload = json.loads(result.stdout or "{}")
        return {"available": True, "findings": payload.get("results", [])}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "semgrep timed out"}
    except (json.JSONDecodeError, OSError) as e:
        return {"available": False, "reason": f"semgrep error: {e}"}


def collect_static_analysis(clone_path: str, config: Config) -> CollectorResult:
    """Run ruff + semgrep against a local clone and return normalized findings."""
    repo_path = Path(clone_path)
    if not repo_path.exists():
        return CollectorResult(
            name="static_analysis",
            status=CollectorStatus.SKIPPED,
            detail="No local clone available",
        )

    timeout = config.collector_timeout_seconds
    findings: List[Dict[str, Any]] = []
    tool_status: Dict[str, str] = {}

    ruff_result = _run_ruff(repo_path, timeout)
    if ruff_result["available"]:
        tool_status["ruff"] = "ok"
        for item in ruff_result["findings"]:
            findings.append(
                {
                    "tool": "ruff",
                    "file": item.get("filename"),
                    "line": item.get("location", {}).get("row"),
                    "rule": item.get("code"),
                    "message": item.get("message"),
                }
            )
    else:
        tool_status["ruff"] = f"skipped: {ruff_result['reason']}"
        logger.info(f"ruff skipped: {ruff_result['reason']}")

    if config.enable_semgrep:
        semgrep_result = _run_semgrep(repo_path, timeout)
        if semgrep_result["available"]:
            tool_status["semgrep"] = "ok"
            for item in semgrep_result["findings"]:
                findings.append(
                    {
                        "tool": "semgrep",
                        "file": item.get("path"),
                        "line": item.get("start", {}).get("line"),
                        "rule": item.get("check_id"),
                        "message": item.get("extra", {}).get("message"),
                        "severity": item.get("extra", {}).get("severity"),
                    }
                )
        else:
            tool_status["semgrep"] = f"skipped: {semgrep_result['reason']}"
            logger.info(f"semgrep skipped: {semgrep_result['reason']}")
    else:
        tool_status["semgrep"] = "disabled by config"

    if not any(v == "ok" for v in tool_status.values()):
        return CollectorResult(
            name="static_analysis",
            status=CollectorStatus.SKIPPED,
            data={"tool_status": tool_status},
            detail="No static analysis tools were available",
        )

    return CollectorResult(
        name="static_analysis",
        status=CollectorStatus.OK,
        data={"findings": findings, "tool_status": tool_status},
    )
