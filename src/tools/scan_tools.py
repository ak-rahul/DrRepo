"""Narrow, on-demand re-run of a single static analysis tool against one path.

Reuses the same subprocess wrappers as the deterministic collectors
(src/collectors/static_analysis.py, src/collectors/security.py) so behavior
stays consistent between the fast recon pass and an investigator's deep dive
-- only the analyzed path differs.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from langchain_core.tools import tool

from src.collectors.security import _run_bandit
from src.collectors.static_analysis import _run_ruff, _run_semgrep
from src.config import Config

_SCANNERS = {"ruff": _run_ruff, "bandit": _run_bandit, "semgrep": _run_semgrep}


def make_scan_tools(clone_root: str, config: Config) -> List:
    """Build a `run_scanner_on_path` tool bound to a clone root and config."""
    root = Path(clone_root).resolve()

    @tool
    def run_scanner_on_path(scanner: str, path: str = ".") -> str:
        """Re-run a static analysis tool against one file or directory, for a closer look.

        Args:
            scanner: One of "ruff", "bandit", "semgrep".
            path: File or directory path relative to the repository root to scan.
        """
        if scanner not in _SCANNERS:
            return f"ERROR: unknown scanner '{scanner}'. Choose from: {sorted(_SCANNERS)}"

        try:
            target = (root / path).resolve()
        except ValueError as e:
            # e.g. an embedded NUL byte -- Path.resolve() raises a bare
            # ValueError for this, and the LLM controls this argument, so it
            # must come back as a normal tool error, not an uncaught exception.
            return f"ERROR: path '{path}' is invalid: {e}"
        if target != root and root not in target.parents:
            return f"ERROR: path '{path}' escapes the repository root"
        if not target.exists():
            return f"ERROR: '{path}' does not exist"

        result = _SCANNERS[scanner](target, config.collector_timeout_seconds)
        if not result["available"]:
            return f"{scanner} unavailable: {result.get('reason', 'unknown reason')}"

        findings = result.get("findings") or result.get("results") or []
        if not findings:
            return f"{scanner} found no issues in '{path}'"
        return "\n".join(str(f) for f in findings[:50])

    return [run_scanner_on_path]
