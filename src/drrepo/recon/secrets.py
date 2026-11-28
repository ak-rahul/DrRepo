"""High-precision secret scanner for committed credentials.

Findings never include the secret itself, only its type and location. Secrets
under test/fixture/example paths are still reported, at LOW severity: test
suites routinely commit throwaway keys (e.g. `tests/certs/server.key`).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix

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


def match_secret(line: str) -> str | None:
    """The secret rule `line` matches, or None. Placeholders and low-entropy values never match."""
    if len(line) > 2000:  # minified bundles; not worth the regex cost
        return None
    for name, pattern, min_entropy in _SECRET_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        value = match.group(match.lastindex or 0)
        if _PLACEHOLDER_RE.search(value) or _shannon_entropy(value) < min_entropy:
            continue
        return name
    return None


def secret_severity(rule: str, rel_path: str) -> str:
    """CRITICAL for a provider key, HIGH for a generic assignment, LOW under test/fixture paths."""
    if is_fixture_path(rel_path):
        return "LOW"
    return "CRITICAL" if rule != "Generic Secret Assignment" else "HIGH"


def is_scannable(rel_path: str) -> bool:
    return not any(rel_path.endswith(s) for s in _SKIP_SUFFIXES)


def scan_secrets(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in iter_repo_files(root):
        rel = relative_posix(path, root)
        if not is_scannable(rel):
            continue
        text = read_text_file(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            name = match_secret(line)
            if name is None:
                continue  # one finding per line at most
            fixture = is_fixture_path(rel)
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
                    "severity": secret_severity(name, rel),
                    "file": rel,
                    "line": line_no,
                }
            )
    return findings
