"""Security collector: bandit (Python), semgrep `p/security-audit` (multi-language),
and a high-precision secret scanner.

`data` schema (status OK): findings: [finding], tool_status: {tool: str}
Secret findings never include the secret itself -- only its type and location.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from drrepo.collectors.filesystem import iter_repo_files, read_text_file, relative_posix
from drrepo.collectors.scanners import run_bandit, run_semgrep
from drrepo.config import Config
from drrepo.core.log import logger
from drrepo.models import CollectorResult, CollectorStatus

NAME = "security"

# (name, regex, entropy threshold). Provider-specific prefixes are precise
# enough on their own; the generic assignment rule needs an entropy floor on
# the captured *value* to stay quiet on placeholders like "your_api_key_here".
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("AWS Access Key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 3.0),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 3.0),
    ("GitHub Fine-Grained Token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"), 3.0),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 3.0),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 3.0),
    ("Stripe Live Key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{24,}\b"), 3.0),
    ("OpenAI API Key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"), 3.5),
    ("Groq API Key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b"), 3.5),
    (
        "Private Key Block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----"),
        0.0,
    ),
    (
        "Generic Secret Assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password|passwd)\b"
            r"\s*[:=]\s*['\"]([A-Za-z0-9_\-+/=]{16,})['\"]"
        ),
        3.5,
    ),
]
_PLACEHOLDER_RE = re.compile(r"(?i)(your|example|sample|dummy|changeme|placeholder|xxxx|test|fake)")
_SKIP_SUFFIXES = {".lock", ".min.js", ".map", ".svg", ".snap"}


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in Counter(s).values())


_FIXTURE_DIRS = {
    "test",
    "tests",
    "testing",
    "testdata",
    "fixtures",
    "__fixtures__",
    "examples",
    "example",
    "samples",
    "mocks",
}


def is_fixture_path(rel_path: str) -> bool:
    """True if a repo-relative path is inside a test/fixture/example directory."""
    return any(part.lower() in _FIXTURE_DIRS for part in rel_path.split("/")[:-1])


def scan_secrets(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in iter_repo_files(root):
        if any(path.name.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        text = read_text_file(path)
        if text is None:
            continue
        rel = relative_posix(path, root)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if len(line) > 2000:  # minified bundles; not worth the regex cost
                continue
            for name, pattern, min_entropy in _SECRET_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group(match.lastindex or 0)
                if _PLACEHOLDER_RE.search(value) or _shannon_entropy(value) < min_entropy:
                    continue
                fixture = is_fixture_path(rel)
                severity = "CRITICAL" if name != "Generic Secret Assignment" else "HIGH"
                findings.append(
                    {
                        "tool": "secret_scan",
                        "rule": name,
                        "message": (
                            f"Possible {name} in a test/fixture path; confirm it is a dummy credential"
                            if fixture
                            else f"Possible {name} committed to source"
                        ),
                        # Test suites routinely commit throwaway keys and certs (e.g.
                        # tests/certs/server.key); still reported, but not as critical.
                        "severity": "LOW" if fixture else severity,
                        "file": rel,
                        "line": line_no,
                    }
                )
                break  # one finding per line is enough
    return findings


def collect_security(clone_path: str, config: Config) -> CollectorResult:
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="No local clone available"
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
            name=NAME,
            status=CollectorStatus.SKIPPED,
            data={"tool_status": tool_status},
            detail="No security scanners were available",
        )
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={"findings": findings, "tool_status": tool_status},
    )
