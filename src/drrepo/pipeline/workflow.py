"""The analysis workflow: recon -> plan -> investigate -> synthesize.

    START -> repo_layout, github_metadata, static_analysis, security, dependency_audit
             github_metadata + repo_layout -> readme   (symmetric depth: no defer)
             (all recon) -> planner            [defer=True]
             planner -> 5 category nodes (parallel; each shallow or deep)
             (all categories) -> synthesizer   [defer=True] -> END

Cloning happens outside the graph (in `execute`) inside try/finally, so the
temp directory is removed no matter how the graph ends.

Fan-in gotcha (verified with a minimal repro): a node whose predecessors sit at
*different* depths fires once per superstep in which any predecessor finishes,
not once after all of them. `readme` finishes a superstep after the other
collectors, so `planner` needs `defer=True`; `synthesizer` gets it too as a
guard. Add `defer=True` to any new multi-predecessor node with asymmetric inputs
-- but don't defer a node that feeds another deferred node (e.g. `readme`):
both then become pending together, the downstream one runs first, and runs
again once the upstream one finishes (observed live: every category ran twice).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from drrepo import __version__
from drrepo.agents.analysts import default_analysts
from drrepo.agents.analysts.base import Analyst, collector_data, merge_issues
from drrepo.agents.investigator import InvestigationError, investigate
from drrepo.agents.llm import LLMRuntime, build_chat_model
from drrepo.agents.planner import LeadInvestigator
from drrepo.collectors.clone import clone_repo
from drrepo.collectors.dependencies import collect_dependency_audit
from drrepo.collectors.github import collect_github_metadata
from drrepo.collectors.layout import collect_repo_layout
from drrepo.collectors.readme import analyze_readme
from drrepo.collectors.security import collect_security
from drrepo.collectors.static_analysis import collect_static_analysis
from drrepo.config import Config
from drrepo.core.budget import LLMBudgetTracker
from drrepo.core.cache import DependencyLookupCache
from drrepo.core.circuit_breaker import CircuitBreaker
from drrepo.core.github_url import parse_github_url
from drrepo.core.log import logger
from drrepo.models import (
    Category,
    CategoryFinding,
    CollectorResult,
    CollectorStatus,
    InvestigationDepth,
    InvestigationPlan,
)
from drrepo.pipeline.state import State
from drrepo.report.synthesizer import synthesize_report
from drrepo.tools.registry import build_tools

ProgressCallback = Callable[[str], None]

COLLECTOR_NODES = (
    "repo_layout",
    "github_metadata",
    "static_analysis",
    "security",
    "dependency_audit",
)
CATEGORY_NODES = {
    Category.DOCUMENTATION: "documentation",
    Category.CODE_QUALITY: "code_quality",
    Category.SECURITY: "security_review",
    Category.DEPENDENCIES: "dependency_review",
    Category.MAINTAINABILITY: "maintainability",
}


def _skipped(name: str, detail: str) -> dict[str, Any]:
    return CollectorResult(name=name, status=CollectorStatus.SKIPPED, detail=detail).to_dict()


class Workflow:
    """Orchestrates analysis runs.

    `llm_breaker`, `llm_budget`, `dependency_cache` default to fresh,
    config-gated instances. A long-lived caller (the Streamlit app) passes the
    *same* breaker and cache into every Workflow so "the provider is down" and
    "we already looked this package up" carry across runs. The budget is reset
    at the start of every `execute()` -- it is a per-run cap.

    One Workflow runs one analysis at a time; `execute` is not re-entrant.
    """

    def __init__(
        self,
        config: Config,
        *,
        llm_client: Any | None = None,
        llm_breaker: CircuitBreaker | None = None,
        llm_budget: LLMBudgetTracker | None = None,
        dependency_cache: DependencyLookupCache | None = None,
        analysts: dict[Category, Analyst] | None = None,
    ):
        self.config = config
        breaker = llm_breaker or (
            CircuitBreaker(
                failure_threshold=config.llm_circuit_breaker_threshold,
                timeout=config.llm_circuit_breaker_timeout_seconds,
                name="llm",
            )
            if config.enable_llm_circuit_breaker
            else None
        )
        budget = llm_budget or (
            LLMBudgetTracker(config.llm_token_budget_per_run)
            if config.enable_llm_budget_tracking
            else None
        )
        if llm_client is None and not config.validate_for_llm():
            llm_client = build_chat_model(config)
        # With no API key configured, `llm.available` is False and every LLM
        # step (narratives, planning, deep dives) is skipped: the report is
        # then fully deterministic rather than the run failing.
        self.llm = LLMRuntime(client=llm_client, breaker=breaker, budget=budget)
        self.dependency_cache = dependency_cache or (
            DependencyLookupCache() if config.enable_dependency_lookup_cache else None
        )
        self.analysts = analysts or default_analysts()
        self.lead_investigator = LeadInvestigator(self.llm)
        self._progress: ProgressCallback = lambda _msg: None
        self.graph = self._build_graph()

    # ---- helpers -----------------------------------------------------------

    def _emit(self, message: str) -> None:
        logger.info(message)
        try:
            self._progress(message)
        except Exception as e:  # a broken UI callback must never break analysis
            logger.debug(f"progress callback failed: {e}")

    # ---- collector nodes ---------------------------------------------------

    def _repo_layout_node(self, state: State) -> dict[str, Any]:
        path = state.get("clone_path")
        if not path:
            return {"collector_results": {"repo_layout": _skipped("repo_layout", "no clone")}}
        self._emit("Mapping repository layout")
        return {"collector_results": {"repo_layout": collect_repo_layout(path).to_dict()}}

    def _github_metadata_node(self, state: State) -> dict[str, Any]:
        self._emit("Fetching GitHub metadata")
        result = collect_github_metadata(state["repo_url"], self.config)
        return {"collector_results": {"github_metadata": result.to_dict()}}

    def _readme_node(self, state: State) -> dict[str, Any]:
        """Analyze the README from the GitHub API, falling back to the clone.

        If neither source produced a README *source*, the readme result is
        SKIPPED -- never an analysis of "" that would falsely report every
        section missing because of an upstream failure.
        """
        results = state["collector_results"]
        github = collector_data(results, "github_metadata")
        layout = collector_data(results, "repo_layout")
        if github is not None and github.get("readme_content"):
            content = github["readme_content"]
        elif layout is not None:
            content = layout.get("readme_content", "")
        elif github is not None:
            content = ""
        else:
            return {
                "collector_results": {"readme": _skipped("readme", "no README source available")}
            }
        return {"collector_results": {"readme": analyze_readme(content).to_dict()}}

    def _static_analysis_node(self, state: State) -> dict[str, Any]:
        path = state.get("clone_path")
        if not path:
            return {
                "collector_results": {"static_analysis": _skipped("static_analysis", "no clone")}
            }
        self._emit("Running ruff")
        return {
            "collector_results": {
                "static_analysis": collect_static_analysis(path, self.config).to_dict()
            }
        }

    def _security_node(self, state: State) -> dict[str, Any]:
        path = state.get("clone_path")
        if not path:
            return {"collector_results": {"security": _skipped("security", "no clone")}}
        self._emit("Running bandit, semgrep and the secret scanner")
        return {"collector_results": {"security": collect_security(path, self.config).to_dict()}}

    def _dependency_audit_node(self, state: State) -> dict[str, Any]:
        path = state.get("clone_path")
        if not path:
            return {
                "collector_results": {"dependency_audit": _skipped("dependency_audit", "no clone")}
            }
        self._emit("Auditing dependencies against OSV.dev")
        result = collect_dependency_audit(path, self.config, cache=self.dependency_cache)
        return {"collector_results": {"dependency_audit": result.to_dict()}}

    # ---- planner -----------------------------------------------------------

    def recon_summary(self, state: State) -> dict[str, Any]:
        """Compact recon signals for the planner (counts, not dumps)."""
        results = state["collector_results"]
        github = collector_data(results, "github_metadata") or {}
        layout = collector_data(results, "repo_layout") or {}
        readme = collector_data(results, "readme") or {}
        static = collector_data(results, "static_analysis")
        security = collector_data(results, "security")
        deps = collector_data(results, "dependency_audit")
        findings = (security or {}).get("findings", [])
        return {
            "language": github.get("language"),
            "lines_by_language": layout.get("lines_by_language"),
            "stars": github.get("stars"),
            "archived": github.get("archived"),
            "file_structure": layout.get("file_structure") or github.get("file_structure"),
            "readme_quality_score": readme.get("quality_score"),
            "readme_missing_sections": readme.get("missing_sections"),
            "static_analysis_findings": len(static["findings"]) if static else "unavailable",
            "security_findings": len(findings) if security is not None else "unavailable",
            "possible_secrets": sum(1 for f in findings if f.get("tool") == "secret_scan"),
            "high_severity_security_findings": sum(
                1
                for f in findings
                if str(f.get("severity", "")).upper() in ("HIGH", "ERROR", "CRITICAL")
            ),
            "dependencies_checked": deps.get("packages_checked") if deps else "unavailable",
            "dependency_vulnerabilities": len(deps.get("vulnerabilities", []))
            if deps
            else "unavailable",
            "unpinned_dependencies": len(deps.get("unpinned", [])) if deps else "unavailable",
            "collector_status": {n: r.get("status") for n, r in results.items()},
        }

    def _planner_node(self, state: State) -> dict[str, Any]:
        if not self.config.enable_deep_investigation:
            return {
                "investigation_plan": InvestigationPlan.all_shallow(
                    "deep investigation disabled by config"
                )
            }
        if not state.get("clone_path"):
            return {
                "investigation_plan": InvestigationPlan.all_shallow(
                    "no clone available to investigate"
                )
            }
        if not self.llm.available:
            return {
                "investigation_plan": InvestigationPlan.all_shallow("no LLM provider configured")
            }

        # Reserve budget up front: the five category nodes run in parallel, so
        # checking the budget inside each node would let all of them see the
        # full budget at the same instant and all go deep.
        budget = self.llm.budget
        max_deep = len(Category)
        if budget is not None:
            max_deep = min(
                max_deep,
                budget.affordable_count(self.config.estimated_tokens_per_deep_investigation),
            )

        self._emit("Lead Investigator is planning the investigation")
        plan = self.lead_investigator.plan(
            self.recon_summary(state), max_deep, state.get("description", "")
        )
        for category, category_plan in plan.plans.items():
            logger.info(
                f"Plan for {category}: {category_plan.depth.value} ({category_plan.rationale})"
            )
        return {"investigation_plan": plan}

    # ---- category nodes ----------------------------------------------------

    def _category_node(self, category: Category) -> Any:
        def node(state: State) -> dict[str, Any]:
            return {
                "category_findings": {category.value: self.run_category(state, category).to_dict()}
            }

        node.__name__ = f"{category.value}_node"
        return node

    def run_category(self, state: State, category: Category) -> CategoryFinding:
        analyst = self.analysts[category]
        recon = state["collector_results"]
        shallow = analyst.run_shallow(recon, self.llm)

        plan: InvestigationPlan = state["investigation_plan"]
        clone_path = state.get("clone_path")
        if plan.depth_for(category) != InvestigationDepth.DEEP or not clone_path:
            self._emit(f"{category.label}: automated pass complete")
            return shallow

        github = collector_data(recon, "github_metadata") or {}
        try:
            full_name = github.get("full_name") or parse_github_url(state["repo_url"]).full_name
        except ValueError:
            full_name = None
        tools = build_tools(
            analyst.tool_families,
            clone_root=clone_path,
            config=self.config,
            cache=self.dependency_cache,
            repo_full_name=full_name,
        )

        self._emit(f"{category.label}: deep investigation started ({len(tools)} tools)")
        try:
            result = investigate(
                category=category,
                system_prompt=analyst.investigation_prompt,
                tools=tools,
                llm=self.llm,
                recon_data={name: r.get("data", {}) for name, r in recon.items()},
                known_issues=shallow.issues,
                max_tool_calls=self.config.max_tool_calls_per_investigator,
                timeout_seconds=self.config.investigator_timeout_seconds,
                user_context=state.get("description", ""),
            )
        except InvestigationError as e:
            self._emit(f"{category.label}: deep investigation {e.reason}; using automated pass")
            shallow.notes.append(
                f"Deep investigation {e.reason}; showing the automated pass instead."
            )
            return shallow

        new_issues = [
            i for i in merge_issues(shallow.issues, result.issues) if i not in shallow.issues
        ]
        assessment = analyst.assess(recon)
        score = (
            analyst.rescore(recon, assessment, new_issues) if assessment.assessed else shallow.score
        )
        self._emit(
            f"{category.label}: deep investigation finished ({len(result.trace)} tool calls, {len(new_issues)} new issues)"
        )
        return CategoryFinding(
            category=category,
            score=score,
            summary=result.summary or shallow.summary,
            issues=merge_issues(shallow.issues, new_issues),
            assessed=shallow.assessed,
            investigation_depth=InvestigationDepth.DEEP,
            investigation_trace=result.trace,
            notes=shallow.notes,
        )

    # ---- synthesizer -------------------------------------------------------

    def _synthesizer_node(self, state: State) -> dict[str, Any]:
        self._emit("Synthesizing report")
        results = state["collector_results"]
        github = collector_data(results, "github_metadata") or {}
        try:
            ref = parse_github_url(state["repo_url"])
            fallback_name, fallback_url = ref.name, ref.html_url
        except ValueError:
            fallback_name, fallback_url = "Unknown", state["repo_url"]
        layout = collector_data(results, "repo_layout") or {}
        languages = list((layout.get("lines_by_language") or {}).keys())
        repository = {
            "name": github.get("name", fallback_name),
            "full_name": github.get("full_name"),
            "url": github.get("url", fallback_url),
            "description": github.get("description", ""),
            "language": github.get("language") or (languages[0] if languages else "Unknown"),
            "stars": github.get("stars", 0),
            "forks": github.get("forks", 0),
            "license": github.get("license_spdx_id"),
        }
        report = synthesize_report(
            repository=repository,
            category_findings={
                k: CategoryFinding.from_dict(v) for k, v in state["category_findings"].items()
            },
            collector_status={
                n: {"status": r.get("status"), "detail": r.get("detail")}
                for n, r in results.items()
            },
            investigation_plan=state["investigation_plan"],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            drrepo_version=__version__,
        )
        return {"report": report.to_dict()}

    # ---- graph -------------------------------------------------------------

    def _build_graph(self) -> Any:
        graph = StateGraph(State)
        graph.add_node("repo_layout", self._repo_layout_node)
        graph.add_node("github_metadata", self._github_metadata_node)
        graph.add_node("static_analysis", self._static_analysis_node)
        graph.add_node("security", self._security_node)
        graph.add_node("dependency_audit", self._dependency_audit_node)
        graph.add_node("readme", self._readme_node)
        graph.add_node("planner", self._planner_node, defer=True)
        for category, node_name in CATEGORY_NODES.items():
            graph.add_node(node_name, self._category_node(category))
        graph.add_node("synthesizer", self._synthesizer_node, defer=True)

        for node in COLLECTOR_NODES:
            graph.add_edge(START, node)
        graph.add_edge("github_metadata", "readme")
        graph.add_edge("repo_layout", "readme")
        for node in ("readme", "static_analysis", "security", "dependency_audit"):
            graph.add_edge(node, "planner")
        for node_name in CATEGORY_NODES.values():
            graph.add_edge("planner", node_name)
            graph.add_edge(node_name, "synthesizer")
        graph.add_edge("synthesizer", END)
        return graph.compile()

    # ---- entrypoint --------------------------------------------------------

    def execute(
        self, repo_url: str, description: str = "", progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        """Analyze `repo_url` and return the report dict (`Report.to_dict()` shape).

        Raises:
            ValueError: `repo_url` isn't a GitHub repository URL.
        """
        ref = parse_github_url(repo_url)
        self._progress = progress or (lambda _msg: None)
        if self.llm.budget is not None:
            self.llm.budget.reset()

        self._emit(f"Cloning {ref.full_name}")
        cloned, clone_result = clone_repo(ref.html_url, self.config)
        initial: State = {
            "repo_url": ref.html_url,
            "description": description,
            "clone_path": str(cloned.path) if cloned else None,
            "collector_results": {"repo_clone": clone_result.to_dict()},
            "investigation_plan": InvestigationPlan.all_shallow("not planned yet"),
            "category_findings": {},
            "report": {},
        }
        try:
            final_state = self.graph.invoke(initial)
            report: dict[str, Any] = final_state["report"]
            if self.llm.budget is not None:
                report["llm_usage"] = self.llm.budget.usage()
            self._emit("Analysis complete")
            return report
        finally:
            if cloned:
                cloned.cleanup()
            self._progress = lambda _msg: None
