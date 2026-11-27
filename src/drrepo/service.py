"""`AnalysisService`: the single façade every interface (CLI, Streamlit, MCP) uses.

One service per process owns everything that should outlive a run:

- one compiled `Workflow` (the graph is stateless, so it is built once);
- one chat-model client;
- the LLM `CircuitBreaker`, so "the provider is down" carries across runs;
- the `DependencyLookupCache`, so a package looked up once is free afterwards;
- the latest report per repository (read by the MCP tools/resources).

Each `analyze()` call gets its own `RunContext` with a fresh `TokenBudget`, so
concurrent runs (Streamlit sessions, MCP calls) never share per-run state.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from drrepo.agents.llm import LLMRuntime, TokenBudget, build_chat_model
from drrepo.config import Config
from drrepo.exporters import EXPORTERS
from drrepo.models import RepoRef
from drrepo.pipeline import ProgressCallback, RunContext, Workflow
from drrepo.recon.dependencies import DependencyLookupCache
from drrepo.reporting import DEFAULT_HISTORY_PATH, attach_and_record_history
from drrepo.resilience import CircuitBreaker

MAX_REPORTS_IN_MEMORY = 20
_UNSET: Any = object()


class AnalysisService:
    def __init__(
        self,
        config: Config,
        *,
        llm_client: Any = _UNSET,
        workflow: Workflow | None = None,
        history_path: Path = DEFAULT_HISTORY_PATH,
    ):
        """`llm_client` defaults to the configured provider's chat model, or None
        (deterministic, no-LLM mode) when its API key is missing."""
        self.config = config
        self.history_path = history_path
        self.workflow = workflow or Workflow()
        if llm_client is _UNSET:
            llm_client = build_chat_model(config) if not config.validate_for_llm() else None
        self.llm_client = llm_client
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

    def new_context(
        self, config: Config | None = None, progress: ProgressCallback | None = None
    ) -> RunContext:
        """A `RunContext` for one run: shared client/breaker/cache, fresh budget."""
        config = config or self.config
        budget = (
            TokenBudget(config.llm_token_budget_per_run)
            if config.enable_llm_budget_tracking
            else None
        )
        context = RunContext(
            config=config,
            llm=LLMRuntime(client=self.llm_client, breaker=self.breaker, budget=budget),
            cache=self.cache,
        )
        if progress is not None:
            context.progress = progress
        return context

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

        `deep=False`/`True` overrides `enable_deep_investigation` for this run
        only. Raises ValueError for a non-GitHub URL.
        """
        repo = RepoRef.parse(repo_url)
        config = self.config
        if deep is not None and deep != config.enable_deep_investigation:
            config = dataclasses.replace(config, enable_deep_investigation=deep)

        report = self.workflow.run(repo, self.new_context(config, progress), description)

        if config.enable_score_history if record_history is None else record_history:
            report = attach_and_record_history(report, self.history_path)

        key = repo.full_name.lower()
        with self._lock:
            self._reports[key] = report
            self._reports.move_to_end(key)
            while len(self._reports) > MAX_REPORTS_IN_MEMORY:
                self._reports.popitem(last=False)
        return report

    def latest_report(self, repo: str) -> dict[str, Any] | None:
        """Most recent report from this process for `repo` (URL or `owner/name`)."""
        url = repo if ("://" in repo or "github.com" in repo) else f"https://github.com/{repo}"
        key = RepoRef.parse(url).full_name.lower()
        with self._lock:
            return self._reports.get(key)

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
    paths = []
    for fmt in formats:
        path = output_dir / f"{slug}_{stamp}.{fmt}"
        path.write_text(EXPORTERS[fmt](report), encoding="utf-8")
        paths.append(path)
    return paths
