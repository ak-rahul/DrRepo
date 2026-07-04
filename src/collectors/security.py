"""Security collector: bandit (Python security) + a lightweight secret scanner.

Like static_analysis.py, this only parses source text -- never executes it.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from src.config import Config
from src.models import CollectorResult, CollectorStatus
from src.utils.logger import logger

# Secret-scanning patterns: (name, regex). Kept intentionally small and
# high-precision to avoid drowning real findings in false positives.
_SECRET_PATTERNS = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack Token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Private Key Block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "Generic API Key Assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
        ),
    ),
]

_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
_MAX_FILE_BYTES = 512_000  # skip scanning unusually large files (binaries, bundles)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _scan_secrets(repo_path: Path) -> List[Dict[str, Any]]:
    findings = []
    for file in repo_path.rglob("*"):
        if not file.is_file():
            continue
        if any(part in _SKIP_DIRS for part in file.parts):
            continue
        try:
            if file.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel_path = str(file.relative_to(repo_path))
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, pattern in _SECRET_PATTERNS:
                match = pattern.search(line)
                if match and _shannon_entropy(match.group(0)) > 2.5:
                    findings.append(
                        {
                            "type": name,
                            "file": rel_path,
                            "line": line_no,
                        }
                    )
    return findings


def _run_bandit(repo_path: Path, timeout: int) -> Dict[str, Any]:
    if shutil.which("bandit") is None:
        return {"available": False, "reason": "bandit not installed"}

    try:
        result = subprocess.run(
            ["bandit", "-r", str(repo_path), "-f", "json", "-q"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # bandit exits non-zero when it finds issues; stdout is still valid JSON.
        payload = json.loads(result.stdout or "{}")
        return {"available": True, "results": payload.get("results", [])}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "bandit timed out"}
    except (json.JSONDecodeError, OSError) as e:
        return {"available": False, "reason": f"bandit error: {e}"}


def collect_security(clone_path: str, config: Config) -> CollectorResult:
    """Run bandit + secret scanning against a local clone."""
    repo_path = Path(clone_path)
    if not repo_path.exists():
        return CollectorResult(
            name="security", status=CollectorStatus.SKIPPED, detail="No local clone available"
        )

    tool_status: Dict[str, str] = {}
    findings: List[Dict[str, Any]] = []

    if config.enable_bandit:
        bandit_result = _run_bandit(repo_path, config.collector_timeout_seconds)
        if bandit_result["available"]:
            tool_status["bandit"] = "ok"
            for item in bandit_result["results"]:
                findings.append(
                    {
                        "tool": "bandit",
                        "file": item.get("filename"),
                        "line": item.get("line_number"),
                        "rule": item.get("test_id"),
                        "message": item.get("issue_text"),
                        "severity": item.get("issue_severity"),
                    }
                )
        else:
            tool_status["bandit"] = f"skipped: {bandit_result['reason']}"
            logger.info(f"bandit skipped: {bandit_result['reason']}")
    else:
        tool_status["bandit"] = "disabled by config"

    try:
        secrets = _scan_secrets(repo_path)
        tool_status["secret_scan"] = "ok"
        for secret in secrets:
            findings.append(
                {
                    "tool": "secret_scan",
                    "file": secret["file"],
                    "line": secret["line"],
                    "rule": secret["type"],
                    "message": f"Possible {secret['type']} committed to source",
                    "severity": "HIGH",
                }
            )
    except Exception as e:
        tool_status["secret_scan"] = f"error: {e}"
        logger.error(f"Secret scan failed: {e}")

    return CollectorResult(
        name="security",
        status=CollectorStatus.OK,
        data={"findings": findings, "tool_status": tool_status},
    )
