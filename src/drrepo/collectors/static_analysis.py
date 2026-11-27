"""Code-quality static analysis (ruff, bug-focused rules) over the local clone.

`data` schema (status OK): findings: [finding], tool_status: {tool: str}
See `drrepo.collectors.scanners` for the finding shape.
"""

from __future__ import annotations

from pathlib import Path

from drrepo.collectors.scanners import run_ruff
from drrepo.config import Config
from drrepo.core.log import logger
from drrepo.models import CollectorResult, CollectorStatus

NAME = "static_analysis"


def collect_static_analysis(clone_path: str, config: Config) -> CollectorResult:
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="No local clone available"
        )

    ruff = run_ruff(root, timeout=config.collector_timeout_seconds)
    if not ruff.available:
        logger.info(f"ruff skipped: {ruff.reason}")
        return CollectorResult(
            name=NAME,
            status=CollectorStatus.SKIPPED,
            data={"tool_status": {"ruff": f"skipped: {ruff.reason}"}},
            detail=f"ruff unavailable: {ruff.reason}",
        )
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={"findings": ruff.findings, "tool_status": {"ruff": "ok"}},
    )
