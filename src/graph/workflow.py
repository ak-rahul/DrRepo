"""DrRepo v3 workflow: parallel collectors (recon) -> Lead Investigator (plans
per-category depth) -> per-category shallow-or-deep routing -> synthesizer.

Cloning happens outside the graph (in `Workflow.execute`) so cleanup is
guaranteed via try/finally regardless of what happens inside the graph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

from langgraph.graph import END, START, StateGraph

from src.agents.base import build_llm_client
from src.agents.code_quality_analyst import CodeQualityAnalyst
from src.agents.dependency_analyst import DependencyAnalyst
from src.agents.docs_analyst import DocsAnalyst
from src.agents.investigator import investigate
from src.agents.maintainability_analyst import MaintainabilityAnalyst
from src.agents.planner import LeadInvestigator
from src.agents.security_analyst import SecurityAnalyst
from src.collectors.dependency_audit import collect_dependency_audit
from src.collectors.github_metadata import collect_github_metadata
from src.collectors.readme import analyze_readme
from src.collectors.repo_clone import clone_repo
from src.collectors.security import collect_security
from src.collectors.static_analysis import collect_static_analysis
from src.config import Config
from src.graph.state import State
from src.models import Category, CollectorResult, InvestigationDepth, InvestigationPlan
from src.report.synthesizer import synthesize_report
from src.tools.dependency_tools import make_dependency_tools
from src.tools.file_tools import make_file_tools
from src.tools.git_tools import make_git_history_tools
from src.tools.scan_tools import make_scan_tools
from src.utils.logger import logger

_INVESTIGATOR_PROMPTS = {
    Category.DOCUMENTATION: (
        "You are investigating documentation quality. Use the file tools to look at the "
        "README and any docs/ directory contents beyond what the automated structural "
        "analysis already found."
    ),
    Category.CODE_QUALITY: (
        "You are investigating code quality. Look for real code smells, complexity issues, "
        "and anti-patterns beyond what the initial ruff/semgrep pass already found -- "
        "especially in files the initial scan flagged, or explore further if nothing stood out."
    ),
    Category.SECURITY: (
        "You are investigating security. Look for real vulnerabilities, hardcoded secrets, "
        "and unsafe patterns beyond what the initial bandit/secret-scan pass found. Check "
        "file history for anything that looks recently and suspiciously added."
    ),
    Category.DEPENDENCIES: (
        "You are investigating dependency health. Inspect manifest files directly and use "
        "the OSV lookup tool to verify and expand on the initial bulk vulnerability scan."
    ),
    Category.MAINTAINABILITY: (
        "You are investigating maintainability. Assess project health, activity, and "
        "structure beyond the basic file-presence checks already collected."
    ),
}


def _collector_status_summary(collector_results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        name: {"status": result.get("status"), "detail": result.get("detail")}
        for name, result in collector_results.items()
    }


def _all_shallow_plan() -> InvestigationPlan:
    from src.models import CategoryPlan

    return InvestigationPlan(
        plans={
            c.value: CategoryPlan(
                category=c,
                depth=InvestigationDepth.SHALLOW,
                rationale="deep investigation disabled",
            )
            for c in Category
        }
    )


class Workflow:
    """Orchestrates a full repository analysis run."""

    def __init__(self, config: Config):
        self.config = config
        llm_client = build_llm_client(config)
        self._llm_client = llm_client

        self.lead_investigator = LeadInvestigator(llm_client)

        self.docs_analyst = DocsAnalyst(llm_client)
        self.code_quality_analyst = CodeQualityAnalyst(llm_client)
        self.security_analyst = SecurityAnalyst(llm_client)
        self.dependency_analyst = DependencyAnalyst(llm_client)
        self.maintainability_analyst = MaintainabilityAnalyst(llm_client)

        self.graph = self._build_graph()

    # ---- collector nodes -------------------------------------------------

    def _github_metadata_node(self, state: State) -> Dict[str, Any]:
        result = collect_github_metadata(state["repo_url"], self.config)
        return {"collector_results": {"github_metadata": _as_dict(result)}}

    def _readme_node(self, state: State) -> Dict[str, Any]:
        github_data = state["collector_results"].get("github_metadata", {}).get("data", {})
        result = analyze_readme(github_data.get("readme_content", ""))
        return {"collector_results": {"readme": _as_dict(result)}}

    def _static_analysis_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        if not clone_path:
            return {
                "collector_results": {
                    "static_analysis": {"status": "skipped", "detail": "no clone"}
                }
            }
        result = collect_static_analysis(clone_path, self.config)
        return {"collector_results": {"static_analysis": _as_dict(result)}}

    def _security_collector_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        if not clone_path:
            return {"collector_results": {"security": {"status": "skipped", "detail": "no clone"}}}
        result = collect_security(clone_path, self.config)
        return {"collector_results": {"security": _as_dict(result)}}

    def _dependency_audit_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        if not clone_path:
            return {
                "collector_results": {
                    "dependency_audit": {"status": "skipped", "detail": "no clone"}
                }
            }
        result = collect_dependency_audit(clone_path, self.config)
        return {"collector_results": {"dependency_audit": _as_dict(result)}}

    # ---- planner -----------------------------------------------------------

    def _collector_data(self, state: State) -> Dict[str, Any]:
        """Unwrap collector_results (status+data) into plain {name: data}."""
        return {name: r.get("data", {}) for name, r in state["collector_results"].items()}

    def _planner_node(self, state: State) -> Dict[str, Any]:
        if not self.config.enable_deep_investigation:
            return {"investigation_plan": _all_shallow_plan()}

        recon_summary = self._recon_summary(state)
        plan = self.lead_investigator.plan(recon_summary)
        for category, category_plan in plan.plans.items():
            logger.info(
                f"Investigation plan for {category}: {category_plan.depth.value} ({category_plan.rationale})"
            )
        return {"investigation_plan": plan}

    def _recon_summary(self, state: State) -> Dict[str, Any]:
        """A compact view of collector data for the planner's prompt -- full
        README text would bloat the prompt for no benefit to a depth decision."""
        data = self._collector_data(state)
        github_data = data.get("github_metadata", {})
        readme_data = data.get("readme", {})
        return {
            "language": github_data.get("language"),
            "stars": github_data.get("stars"),
            "file_structure": github_data.get("file_structure"),
            "readme_quality_score": readme_data.get("quality_score"),
            "readme_missing_sections": readme_data.get("missing_sections"),
            "static_analysis_findings": len(data.get("static_analysis", {}).get("findings", [])),
            "security_findings": len(data.get("security", {}).get("findings", [])),
            "dependency_vulnerabilities": len(
                data.get("dependency_audit", {}).get("vulnerabilities", [])
            ),
        }

    # ---- per-category routing (shallow analyst vs. deep investigator) -----

    def _run_category(
        self,
        state: State,
        category: Category,
        shallow_analyst: Any,
        tools: List[Any],
    ) -> Dict[str, Any]:
        plan: InvestigationPlan = state["investigation_plan"]
        clone_path = state.get("clone_path")

        go_deep = (
            self.config.enable_deep_investigation
            and plan.depth_for(category) == InvestigationDepth.DEEP
            and clone_path is not None
        )

        if go_deep:
            findings = investigate(
                category=category,
                system_prompt=_INVESTIGATOR_PROMPTS[category],
                tools=tools,
                llm_client=self._llm_client,
                recon_data=self._collector_data(state),
                max_tool_calls=self.config.max_tool_calls_per_investigator,
            )
        else:
            findings = shallow_analyst.analyze(self._collector_data(state))

        return {"category_findings": {category.value: findings}}

    def _docs_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        tools = make_file_tools(clone_path) if clone_path else []
        return self._run_category(state, Category.DOCUMENTATION, self.docs_analyst, tools)

    def _code_quality_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        tools = (
            (make_file_tools(clone_path) + make_scan_tools(clone_path, self.config))
            if clone_path
            else []
        )
        return self._run_category(state, Category.CODE_QUALITY, self.code_quality_analyst, tools)

    def _security_analyst_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        tools: List[Any] = []
        if clone_path:
            tools = make_file_tools(clone_path) + make_scan_tools(clone_path, self.config)
            full_name = (
                state["collector_results"]
                .get("github_metadata", {})
                .get("data", {})
                .get("full_name")
            )
            if full_name:
                tools += make_git_history_tools(full_name, self.config)
        return self._run_category(state, Category.SECURITY, self.security_analyst, tools)

    def _dependency_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        tools = (
            (make_file_tools(clone_path) + make_dependency_tools(self.config)) if clone_path else []
        )
        return self._run_category(state, Category.DEPENDENCIES, self.dependency_analyst, tools)

    def _maintainability_node(self, state: State) -> Dict[str, Any]:
        clone_path = state.get("clone_path")
        tools: List[Any] = []
        if clone_path:
            tools = make_file_tools(clone_path)
            full_name = (
                state["collector_results"]
                .get("github_metadata", {})
                .get("data", {})
                .get("full_name")
            )
            if full_name:
                tools += make_git_history_tools(full_name, self.config)
        return self._run_category(
            state, Category.MAINTAINABILITY, self.maintainability_analyst, tools
        )

    # ---- synthesizer -------------------------------------------------------

    def _synthesizer_node(self, state: State) -> Dict[str, Any]:
        github_data = state["collector_results"].get("github_metadata", {}).get("data", {})
        repository = {
            "name": github_data.get("name", "Unknown"),
            "url": github_data.get("url", state["repo_url"]),
            "language": github_data.get("language", "Unknown"),
            "stars": github_data.get("stars", 0),
            "forks": github_data.get("forks", 0),
        }
        report = synthesize_report(
            repository=repository,
            category_findings=state["category_findings"],
            collector_status=_collector_status_summary(state["collector_results"]),
        )
        return {"report": report.to_dict()}

    # ---- graph assembly -----------------------------------------------------

    def _build_graph(self) -> Any:
        graph = StateGraph(State)

        graph.add_node("github_metadata", self._github_metadata_node)
        graph.add_node("readme", self._readme_node)
        graph.add_node("static_analysis", self._static_analysis_node)
        graph.add_node("security_collector", self._security_collector_node)
        graph.add_node("dependency_audit", self._dependency_audit_node)

        # `defer=True`: "readme" completes one superstep later than the other
        # three collectors (it depends on github_metadata), so without this a
        # fan-in node fires once per superstep in which *any* predecessor
        # newly completes -- twice here -- rather than once after all of them
        # are done. Verified with a minimal repro against the installed
        # langgraph version before relying on it; see CLAUDE.md.
        graph.add_node("planner", self._planner_node, defer=True)

        graph.add_node("docs", self._docs_node)
        graph.add_node("code_quality", self._code_quality_node)
        graph.add_node("security_analyst", self._security_analyst_node)
        graph.add_node("dependency_analyst", self._dependency_node)
        graph.add_node("maintainability", self._maintainability_node)

        # All 5 category nodes are exactly one hop from "planner" (symmetric
        # depth), so no defer needed here -- included anyway as a defensive
        # guard against future topology changes.
        graph.add_node("synthesizer", self._synthesizer_node, defer=True)

        # Parallel collector (recon) fan-out from START.
        graph.add_edge(START, "github_metadata")
        graph.add_edge(START, "static_analysis")
        graph.add_edge(START, "security_collector")
        graph.add_edge(START, "dependency_audit")
        # readme depends on github_metadata's fetched content.
        graph.add_edge("github_metadata", "readme")

        # Fan-in: the planner waits for every collector to finish, then plans
        # per-category depth from the full recon picture.
        collector_nodes = ["readme", "static_analysis", "security_collector", "dependency_audit"]
        for collector_node in collector_nodes:
            graph.add_edge(collector_node, "planner")

        # Fan-out: every category node runs in parallel, each deciding for
        # itself (via `_run_category`) whether to go shallow or deep per the plan.
        category_nodes = [
            "docs",
            "code_quality",
            "security_analyst",
            "dependency_analyst",
            "maintainability",
        ]
        for category_node in category_nodes:
            graph.add_edge("planner", category_node)
            graph.add_edge(category_node, "synthesizer")

        graph.add_edge("synthesizer", END)

        return graph.compile()

    # ---- public entrypoint --------------------------------------------------

    def execute(self, repo_url: str, description: str = "") -> Dict[str, Any]:
        """Run a full analysis of `repo_url` and return the final report dict."""
        logger.info(f"Starting analysis for {repo_url}")

        cloned, clone_result = clone_repo(repo_url, self.config)
        clone_path: Optional[str] = str(cloned.path) if cloned else None

        initial_state: State = {
            "repo_url": repo_url,
            "description": description,
            "clone_path": clone_path,
            "collector_results": {"repo_clone": _as_dict(clone_result)},
            "investigation_plan": _all_shallow_plan(),
            "category_findings": {},
            "report": {},
            "errors": [],
        }

        try:
            # `self.graph` is typed `Any` (LangGraph's compiled graph type is
            # not easily expressible here), so cast the one value we actually
            # return rather than let `Any` leak through this method's signature.
            final_state = self.graph.invoke(initial_state)
            logger.info("Analysis complete")
            return cast(Dict[str, Any], final_state["report"])
        finally:
            if cloned:
                cloned.cleanup()


def _as_dict(result: CollectorResult) -> Dict[str, Any]:
    return {"status": result.status.value, "data": result.data, "detail": result.detail}
