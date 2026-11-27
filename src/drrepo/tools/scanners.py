"""`run_scanner_on_path`: re-run ruff/bandit/semgrep on one file or directory.

Reuses `drrepo.collectors.scanners`, so the deep dive and the recon pass agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from drrepo.collectors.scanners import SCANNERS
from drrepo.config import Config
from drrepo.tools.files import PathEscapesSandboxError, resolve_safe_path

MAX_FINDINGS_SHOWN = 40


def make_scan_tools(clone_root: str, config: Config) -> list[Any]:
    root = Path(clone_root).resolve()

    @tool
    def run_scanner_on_path(scanner: str, path: str = ".") -> str:
        """Re-run a static analysis tool on one file or directory for a closer look.

        Args:
            scanner: "ruff" (Python bugs/lint), "bandit" (Python security), or "semgrep" (multi-language security).
            path: File or directory relative to the repository root.
        """
        if scanner not in SCANNERS:
            return f"ERROR: unknown scanner '{scanner}'. Choose from: {sorted(SCANNERS)}"
        if scanner == "semgrep" and not config.enable_semgrep:
            return "semgrep is disabled by configuration"
        if scanner == "bandit" and not config.enable_bandit:
            return "bandit is disabled by configuration"
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: '{path}' does not exist"

        result = SCANNERS[scanner](root, target, timeout=config.collector_timeout_seconds)
        if not result.available:
            return f"{scanner} unavailable: {result.reason}"
        if not result.findings:
            return f"{scanner} found no issues in '{path}'"
        lines = [
            f"{f['file']}:{f.get('line')}: [{f.get('severity') or '-'}] {f.get('rule')}: {f.get('message', '')[:200]}"
            for f in result.findings[:MAX_FINDINGS_SHOWN]
        ]
        if len(result.findings) > MAX_FINDINGS_SHOWN:
            lines.append(f"... and {len(result.findings) - MAX_FINDINGS_SHOWN} more")
        return "\n".join(lines)

    return [run_scanner_on_path]
