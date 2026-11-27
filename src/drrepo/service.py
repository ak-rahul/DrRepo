"""`AnalysisService`: the single façade every interface (CLI, Streamlit, MCP) uses.

It owns the collaborators that should outlive one run -- the LLM circuit
breaker and the dependency lookup cache -- and builds a fresh `Workflow` (with
a fresh per-run token budget) for every analysis. It also records score
history and keeps the most recent report per repository in memory, which is
what the MCP server's `get_report` tool and report resources read.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.core.cache import DependencyLookupCache
from drrepo.core.circuit_breaker import CircuitBreaker
from drrepo.core.github_url import parse_github_url
from drrepo.pipeline.workflow import ProgressCallback, Workflow
from drrepo.report.exporters import EXPORTERS
from drrepo.report.history import DEFAULT_HISTORY_PATH, attach_and_record_history

MAX_REPORTS_IN_MEMORY = 20


class AnalysisService:
    def __init__(
        self,
        config: Config,
        *,
        llm_client: Any | None = None,
        history_path: Path = DEFAULT_HISTORY_PATH,
    ):
        self.config = config
        self.history_path = history_path
        self._llm_client = llm_client
        self.breaker = (
            CircuitBreaker(
                failure_threshold=config.llm_circuit_breaker_threshold,
                timeout=config.llm_circuit_breaker_timeout_seconds,
                name="llm",
            )
            if config.enable_llm_circuit_breaker
            else None
        )
        self.cache = DependencyLookupCache() if config.enable_dependency_lookup_cache else None
        self._reports: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def analyze(
        self,
        repo_url: str,
        description: str = "",
        *,
        deep: bool | None = None,
        record_history: bool | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Run one analysis and return the report dict.

        `deep=False` forces the all-shallow path for this run only; `None` uses
        the configured default. Raises ValueError for a non-GitHub URL.
        """
        ref = parse_github_url(repo_url)
        config = self.config
        if deep is not None and deep != config.enable_deep_investigation:
            config = dataclasses.replace(config, enable_deep_investigation=deep)

        workflow = Workflow(
            config,
            llm_client=self._llm_client,
            llm_breaker=self.breaker,
            dependency_cache=self.cache,
        )
        report = workflow.execute(ref.html_url, description, progress=progress)

        if record_history if record_history is not None else config.enable_score_history:
            report = attach_and_record_history(report, self.history_path)

        with self._lock:
            self._reports[ref.full_name.lower()] = report
            self._reports.move_to_end(ref.full_name.lower())
            while len(self._reports) > MAX_REPORTS_IN_MEMORY:
                self._reports.popitem(last=False)
        return report

    def latest_report(self, repo: str) -> dict[str, Any] | None:
        """Most recent report from this process for `repo` (URL or `owner/name`)."""
        key = (
            repo
            if "/" in repo and "://" not in repo and "github.com" not in repo
            else parse_github_url(repo).full_name
        )
        with self._lock:
            return self._reports.get(key.lower())

    def list_reports(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "repository": name,
                    "overall_score": r.get("overall_score"),
                    "generated_at": r.get("generated_at"),
                    "issue_counts": r.get("issue_counts"),
                }
                for name, r in reversed(self._reports.items())
            ]

    def breaker_state(self) -> dict[str, Any] | None:
        return self.breaker.get_state() if self.breaker else None


def save_report(
    report: dict[str, Any], output_dir: Path, formats: tuple[str, ...] = ("json", "md", "sarif")
) -> list[Path]:
    """Write `report` in each requested format; returns the written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    repo = report.get("repository", {})
    slug = (repo.get("full_name") or repo.get("name") or "repository").replace("/", "__")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    written = []
    for fmt in formats:
        path = output_dir / f"{slug}_{stamp}.{fmt}"
        path.write_text(EXPORTERS[fmt](report), encoding="utf-8")
        written.append(path)
    return written
