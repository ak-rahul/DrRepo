"""DrRepo v2 workflow: parallel collectors -> parallel analyst agents -> synthesizer.

Cloning happens outside the graph (in `Workflow.execute`) so cleanup is
guaranteed via try/finally regardless of what happens inside the graph.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, cast

from langgraph.graph import END, START, StateGraph

from src.agents.base import build_llm_client
from src.agents.code_quality_analyst import CodeQualityAnalyst
from src.agents.dependency_analyst import DependencyAnalyst
from src.agents.docs_analyst import DocsAnalyst
from src.agents.maintainability_analyst import MaintainabilityAnalyst
from src.agents.security_analyst import SecurityAnalyst
from src.collectors.dependency_audit import collect_dependency_audit
from src.collectors.github_metadata import collect_github_metadata
from src.collectors.readme import analyze_readme
from src.collectors.repo_clone import clone_repo
from src.collectors.security import collect_security
from src.collectors.static_analysis import collect_static_analysis
from src.config import Config
from src.graph.state import State
from src.models import Category, CollectorResult
from src.report.synthesizer import synthesize_report
from src.utils.logger import logger


def _collector_status_summary(collector_results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        name: {"status": result.get("status"), "detail": result.get("detail")}
        for name, result in collector_results.items()
    }


class Workflow:
    """Orchestrates a full repository analysis run."""

    def __init__(self, config: Config):
        self.config = config
        llm_client = build_llm_client(config)

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

    def _security_node(self, state: State) -> Dict[str, Any]:
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

    # ---- analyst nodes -----------------------------------------------------

    def _collector_data(self, state: State) -> Dict[str, Any]:
        """Unwrap collector_results (status+data) into plain {name: data} for analysts."""
        return {name: r.get("data", {}) for name, r in state["collector_results"].items()}

    def _docs_analyst_node(self, state: State) -> Dict[str, Any]:
        findings = self.docs_analyst.analyze(self._collector_data(state))
        return {"category_findings": {Category.DOCUMENTATION.value: findings}}

    def _code_quality_analyst_node(self, state: State) -> Dict[str, Any]:
        findings = self.code_quality_analyst.analyze(self._collector_data(state))
        return {"category_findings": {Category.CODE_QUALITY.value: findings}}

    def _security_analyst_node(self, state: State) -> Dict[str, Any]:
        findings = self.security_analyst.analyze(self._collector_data(state))
        return {"category_findings": {Category.SECURITY.value: findings}}

    def _dependency_analyst_node(self, state: State) -> Dict[str, Any]:
        findings = self.dependency_analyst.analyze(self._collector_data(state))
        return {"category_findings": {Category.DEPENDENCIES.value: findings}}

    def _maintainability_analyst_node(self, state: State) -> Dict[str, Any]:
        findings = self.maintainability_analyst.analyze(self._collector_data(state))
        return {"category_findings": {Category.MAINTAINABILITY.value: findings}}

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
        graph.add_node("security", self._security_node)
        graph.add_node("dependency_audit", self._dependency_audit_node)

        graph.add_node("docs_analyst", self._docs_analyst_node)
        graph.add_node("code_quality_analyst", self._code_quality_analyst_node)
        graph.add_node("security_analyst", self._security_analyst_node)
        graph.add_node("dependency_analyst", self._dependency_analyst_node)
        graph.add_node("maintainability_analyst", self._maintainability_analyst_node)

        graph.add_node("synthesizer", self._synthesizer_node)

        # Parallel collector fan-out from START.
        graph.add_edge(START, "github_metadata")
        graph.add_edge(START, "static_analysis")
        graph.add_edge(START, "security")
        graph.add_edge(START, "dependency_audit")
        # readme depends on github_metadata's fetched content.
        graph.add_edge("github_metadata", "readme")

        # Fan-in: every analyst waits for all collectors to complete.
        collector_nodes = ["readme", "static_analysis", "security", "dependency_audit"]
        analyst_nodes = [
            "docs_analyst",
            "code_quality_analyst",
            "security_analyst",
            "dependency_analyst",
            "maintainability_analyst",
        ]
        for collector_node in collector_nodes:
            for analyst_node in analyst_nodes:
                graph.add_edge(collector_node, analyst_node)

        for analyst_node in analyst_nodes:
            graph.add_edge(analyst_node, "synthesizer")

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
