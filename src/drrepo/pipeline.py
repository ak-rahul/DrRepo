"""The analysis graph: recon -> plan -> investigate -> synthesize.

    START ─┬─ repo_layout ─────┐
           ├─ github_metadata ─┴─► readme ─┐
           ├─ static_analysis ─────────────┤
           ├─ security ────────────────────┼─► planner ─► 5 category nodes ─► synthesizer ─► END
           └─ dependency_audit ────────────┘

Design:
- **Compiled once, run many times.** `Workflow` holds no per-run state. Every
  run-specific collaborator (config, LLM runtime with a fresh token budget,
  dependency cache, progress callback) travels in a `RunContext` through
  LangGraph's runtime context, so one compiled graph serves concurrent runs.
- **Recon is declarative.** `COLLECTORS` lists `CollectorSpec`s; the graph is
  generated from them. A spec that needs a clone is skipped uniformly when
  there is none.
- **Typed state.** Nodes exchange `CollectorResult`/`CategoryFinding` objects;
  only the final `Report` is converted to a dict.
- **Cloning happens outside the graph**, in `Workflow.run`, inside try/finally.

Fan-in gotcha (verified): a node whose predecessors sit at *different* depths
fires once per superstep in which any predecessor finishes, unless it has
`defer=True`. `_needs_defer` decides that from the topology. Never defer a node
that feeds another deferred node: both become pending together, the downstream
one runs first and then again (observed live: every category ran twice).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from drrepo import __version__
from drrepo.agents.analysts import default_analysts
from drrepo.agents.analysts.base import Analyst, Recon, collector_data, merge_issues
from drrepo.agents.critic import review as critic_review
from drrepo.agents.grounding import ground_issues
from drrepo.agents.investigator import investigate
from drrepo.agents.llm import LLMRuntime
from drrepo.agents.planner import LeadInvestigator, restrict_plan
from drrepo.agents.symbols import SymbolIndex
from drrepo.agents.tools import build_tools
from drrepo.config import Config
from drrepo.errors import InvestigationError
from drrepo.log import logger
from drrepo.models import (
    Category,
    CategoryFinding,
    CollectorResult,
    CollectorStatus,
    InvestigationDepth,
    InvestigationPlan,
    RepoRef,
    Report,
)
from drrepo.recon.clone import clone_repo
from drrepo.recon.dependencies import DependencyLookupCache, collect_dependency_audit
from drrepo.recon.doc_checks import collect_doc_checks
from drrepo.recon.files import collect_repo_layout
from drrepo.recon.github import collect_github_metadata
from drrepo.recon.infrastructure import collect_infrastructure
from drrepo.recon.readme import analyze_readme
from drrepo.recon.scanners import collect_security, collect_static_analysis
from drrepo.recon.scorecard import collect_scorecard
from drrepo.report.provenance import build_provenance
from drrepo.report.suppressions import (
    REPOSITORY_FILE,
    Suppression,
    SuppressionError,
    SuppressionResult,
)
from drrepo.report.suppressions import apply as apply_suppressions
from drrepo.report.suppressions import load_file as load_suppression_file
from drrepo.report.synthesis import dependency_inventory, synthesize_report

ProgressCallback = Callable[[str], None]


def _no_progress(_message: str) -> None:
    return None


# ------------------------------------------------------------- context ---


@dataclass
class RunContext:
    """Everything one run needs besides graph state. Built by `AnalysisService`."""

    config: Config
    llm: LLMRuntime
    cache: DependencyLookupCache | None = None
    progress: ProgressCallback = field(default=_no_progress)
    # Suppressions you passed (always applied); the repo's own are added in `Workflow.run`.
    suppressions: list[Suppression] = field(default_factory=list)
    # Measured cost of one deep investigation (from score history); None means
    # use `config.estimated_tokens_per_deep_investigation`.
    deep_investigation_tokens: int | None = None
    # Categories the plan may investigate with tools; None means all (diff mode
    # passes only the categories that got worse).
    deep_allowed: frozenset[str] | None = None
    # The clone's symbol index, shared by every investigation of this run (built
    # lazily on the first symbol tool call). Set by `Workflow.run`.
    symbol_index: SymbolIndex | None = None

    def deep_estimate(self) -> tuple[int, str]:
        """Tokens one deep investigation is expected to cost, and where that came from."""
        if self.deep_investigation_tokens:
            return self.deep_investigation_tokens, "history"
        return self.config.estimated_tokens_per_deep_investigation, "config"

    def emit(self, message: str) -> None:
        logger.info(message)
        try:
            self.progress(message)
        except Exception as e:  # a broken UI callback must never break an analysis
            logger.debug(f"progress callback failed: {e}")


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class State(TypedDict):
    repo: RepoRef
    description: str
    clone_path: str | None
    suppressions: list[Suppression]
    collector_results: Annotated[dict[str, CollectorResult], _merge]
    investigation_plan: InvestigationPlan
    category_findings: Annotated[dict[str, CategoryFinding], _merge]
    report: Report | None


# ---------------------------------------------------------- collectors ---


@dataclass(frozen=True)
class CollectorSpec:
    name: str
    run: Callable[[State, RunContext], CollectorResult]
    progress: str | None = None
    needs_clone: bool = False
    after: tuple[str, ...] = ()


def _readme(state: State, ctx: RunContext) -> CollectorResult:
    """README from the clone (the exact commit analyzed), falling back to the GitHub
    API, which always serves the default branch's HEAD. SKIPPED (never an analysis
    of "") when neither source is available -- otherwise an upstream failure would
    be reported as "every section missing"."""
    github = collector_data(state["collector_results"], "github_metadata")
    layout = collector_data(state["collector_results"], "repo_layout")
    if layout is not None and layout.get("readme_content"):
        return analyze_readme(layout["readme_content"])
    if github is not None and github.get("readme_content"):
        return analyze_readme(github["readme_content"])
    if layout is not None:
        return analyze_readme("")
    if github is not None:
        return analyze_readme("")
    return CollectorResult.skipped("readme", "no README source available")


COLLECTORS: tuple[CollectorSpec, ...] = (
    CollectorSpec(
        "repo_layout",
        lambda s, c: collect_repo_layout(s["clone_path"] or ""),
        "Mapping repository layout",
        needs_clone=True,
    ),
    CollectorSpec(
        "github_metadata",
        lambda s, c: collect_github_metadata(s["repo"].html_url, c.config),
        "Fetching GitHub metadata",
    ),
    CollectorSpec(
        "static_analysis",
        lambda s, c: collect_static_analysis(s["clone_path"] or "", c.config),
        "Running ruff",
        needs_clone=True,
    ),
    CollectorSpec(
        "security",
        lambda s, c: collect_security(s["clone_path"] or "", c.config),
        "Running bandit, semgrep and the secret scanner",
        needs_clone=True,
    ),
    CollectorSpec(
        "dependency_audit",
        lambda s, c: collect_dependency_audit(s["clone_path"] or "", c.config, cache=c.cache),
        "Auditing dependencies against OSV.dev",
        needs_clone=True,
    ),
    CollectorSpec(
        "infrastructure",
        lambda s, c: collect_infrastructure(s["clone_path"] or "", c.config),
        "Auditing CI workflows and Dockerfiles",
        needs_clone=True,
    ),
    CollectorSpec(
        "scorecard",
        lambda s, c: collect_scorecard(s["repo"].html_url, c.config),
        "Fetching OpenSSF Scorecard",
    ),
    CollectorSpec(
        "doc_checks",
        lambda s, c: collect_doc_checks(s["clone_path"] or ""),
        "Checking documentation links, docstrings and commands",
        needs_clone=True,
    ),
    CollectorSpec("readme", _readme, after=("github_metadata", "repo_layout")),
)


def _depths(specs: tuple[CollectorSpec, ...]) -> dict[str, int]:
    by_name = {s.name: s for s in specs}
    depths: dict[str, int] = {}

    def depth(name: str) -> int:
        if name not in depths:
            depths[name] = 1 + max((depth(p) for p in by_name[name].after), default=0)
        return depths[name]

    for spec in specs:
        depth(spec.name)
    return depths


def _needs_defer(predecessor_depths: list[int]) -> bool:
    return len(set(predecessor_depths)) > 1


# ------------------------------------------------------------ workflow ---


class Workflow:
    """A compiled analysis graph. Stateless between runs; safe to share."""

    def __init__(
        self,
        analysts: dict[Category, Analyst] | None = None,
        collectors: tuple[CollectorSpec, ...] = COLLECTORS,
    ):
        self.analysts = analysts or default_analysts()
        self.collectors = collectors
        self.graph = self._build_graph()

    # ---- nodes -------------------------------------------------------------

    @staticmethod
    def _collector_node(
        spec: CollectorSpec,
    ) -> Callable[[State, Runtime[RunContext]], dict[str, Any]]:
        def node(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
            ctx = runtime.context
            if spec.needs_clone and not state["clone_path"]:
                result = CollectorResult.skipped(spec.name, "no clone")
            else:
                if spec.progress:
                    ctx.emit(spec.progress)
                try:
                    result = spec.run(state, ctx)
                except Exception as e:
                    # Collectors report expected failures as skipped/error results; this
                    # is the safety net for unexpected ones, so one bad signal can never
                    # take the whole analysis down.
                    logger.exception(f"collector {spec.name} crashed")
                    result = CollectorResult(
                        spec.name,
                        CollectorStatus.ERROR,
                        detail=f"unexpected error: {type(e).__name__}: {str(e)[:200]}",
                    )
            return {"collector_results": {spec.name: result}}

        return node

    def _planner_node(self, state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
        ctx = runtime.context
        reason = None
        if not ctx.config.enable_deep_investigation:
            reason = "deep investigation disabled by config"
        elif not state["clone_path"]:
            reason = "no clone available to investigate"
        elif not ctx.llm.available:
            reason = "no LLM provider configured"
        elif ctx.deep_allowed is not None and not ctx.deep_allowed:
            reason = "no category changed since the base commit"
        if reason:
            return {"investigation_plan": InvestigationPlan.all_shallow(reason)}

        # Reserve budget before the parallel fan-out: checking it inside each
        # category node would let all five see a full budget at the same
        # instant and all go deep. One unit is half a deep investigation
        # (a lite one), priced from measured history where available.
        max_units = len(Category) * InvestigationDepth.DEEP.budget_units
        if ctx.llm.budget is not None:
            estimate, _source = ctx.deep_estimate()
            unit_cost = max(1, estimate // InvestigationDepth.DEEP.budget_units)
            max_units = min(max_units, ctx.llm.budget.affordable_count(unit_cost))

        ctx.emit("Lead Investigator is planning the investigation")
        plan = LeadInvestigator(ctx.llm.for_role("planner")).plan(
            recon_summary(state["collector_results"]), max_units, state["description"]
        )
        if ctx.deep_allowed is not None:
            plan = restrict_plan(plan, ctx.deep_allowed)
        for name, p in plan.plans.items():
            logger.info(f"Plan for {name}: {p.depth.value} ({p.rationale})")
        return {"investigation_plan": plan}

    def _category_node(
        self, category: Category
    ) -> Callable[[State, Runtime[RunContext]], dict[str, Any]]:
        def node(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
            finding = self.analyze_category(category, state, runtime.context)
            return {"category_findings": {category.value: finding}}

        return node

    def analyze_category(
        self, category: Category, state: State, ctx: RunContext
    ) -> CategoryFinding:
        """Deterministic assessment, then (if planned) a deep investigation on top of it."""
        analyst = self.analysts[category]
        recon = state["collector_results"]
        today = datetime.now(UTC).date()
        assessment = analyst.assess(recon)
        if ctx.config.enable_llm_judgment and ctx.llm.available:
            # Structured judgment shares the planner's model (both are structured outputs).
            assessment = analyst.judge(
                recon,
                assessment,
                ctx.llm.for_role("planner", label="judgment"),
                state["clone_path"],
            )
        recon_supp = apply_suppressions(assessment.issues, state["suppressions"], today)
        if recon_supp.suppressed or recon_supp.expired:
            rescored = (
                analyst.score_issues(recon, recon_supp.kept)
                if recon_supp.suppressed and assessment.assessed
                else None
            )
            assessment = dataclasses.replace(
                assessment,
                issues=recon_supp.kept,
                score=assessment.score if rescored is None else rescored,
                notes=[*assessment.notes, *recon_supp.notes()],
            )
        shallow = analyst.narrate(assessment, ctx.llm.for_role("narrative"))
        shallow.suppressed = _suppressed_entries(recon_supp)

        depth = state["investigation_plan"].depth_for(category)
        if not depth.investigates or not state["clone_path"]:
            ctx.emit(f"{category.label}: automated pass complete")
            return shallow
        max_tool_calls = ctx.config.max_tool_calls_per_investigator
        if depth is InvestigationDepth.LITE:
            max_tool_calls = max(1, max_tool_calls // 2)

        tools = build_tools(
            analyst.tool_families,
            clone_root=state["clone_path"],
            config=ctx.config,
            cache=ctx.cache,
            repo_full_name=state["repo"].full_name,
            symbol_index=ctx.symbol_index,
        )
        ctx.emit(f"{category.label}: {depth.value} investigation started ({len(tools)} tools)")
        try:
            result = investigate(
                category=category,
                system_prompt=analyst.investigation_prompt,
                tools=tools,
                llm=ctx.llm.for_role("investigation", label=f"investigation:{category.value}"),
                recon_data={name: r.data for name, r in recon.items()},
                known_issues=shallow.issues,
                max_tool_calls=max_tool_calls,
                timeout_seconds=ctx.config.investigator_timeout_seconds,
                user_context=state["description"],
            )
        except InvestigationError as e:
            ctx.emit(
                f"{category.label}: {depth.value} investigation {e.reason}; using automated pass"
            )
            shallow.notes.append(
                f"{depth.value.capitalize()} investigation {e.reason}; showing the automated pass instead."
            )
            return shallow

        grounding = ground_issues(
            result.issues,
            clone_root=state["clone_path"],
            trace=result.trace,
            evidence=result.evidence,
        )
        for issue, reason in grounding.dropped:
            logger.info(f"{category.value}: dropped agent finding {issue.title!r}: {reason}")
        agent_issues = grounding.kept
        critic_note = None
        if ctx.config.enable_agent_critic:
            critique = critic_review(ctx.llm.for_role("critic"), agent_issues, state["clone_path"])
            agent_issues, critic_note = critique.issues, critique.note()
        agent_supp = apply_suppressions(agent_issues, state["suppressions"], today)
        known = {i.dedupe_key() for i in shallow.issues}
        new_issues = [i for i in agent_supp.kept if i.dedupe_key() not in known]
        ctx.emit(
            f"{category.label}: {depth.value} investigation finished "
            f"({len(result.trace)} tool calls, {len(new_issues)} new issues)"
        )
        notes = list(shallow.notes)
        if note := grounding.note():
            notes.append(note)
        if critic_note:
            notes.append(critic_note)
        return CategoryFinding(
            category=category,
            score=analyst.rescore(recon, assessment, new_issues)
            if assessment.assessed
            else shallow.score,
            summary=result.summary or shallow.summary,
            issues=merge_issues(shallow.issues, new_issues),
            assessed=shallow.assessed,
            investigation_depth=depth,
            investigation_trace=result.trace,
            notes=notes,
            suppressed=shallow.suppressed + _suppressed_entries(agent_supp),
        )

    @staticmethod
    def _load_suppressions(
        ctx: RunContext, clone: Path | None
    ) -> tuple[list[Suppression], CollectorResult]:
        """Your suppressions, plus the repository's own `.drrepo.toml` when trusted.

        The outcome is recorded as a `suppressions` entry in collector status, so a
        report always says which suppressions applied, and why a repo file didn't.
        """
        suppressions = list(ctx.suppressions)
        data = {"local": len(suppressions), "repository": 0}
        detail = None
        repo_file = clone / REPOSITORY_FILE if clone else None
        if repo_file is not None and repo_file.is_file():
            if not ctx.config.trust_repo_suppressions:
                detail = f"repository {REPOSITORY_FILE} ignored (TRUST_REPO_SUPPRESSIONS is off)"
            else:
                try:
                    from_repo = load_suppression_file(repo_file, origin="repository")
                except SuppressionError as e:
                    return suppressions, CollectorResult(
                        "suppressions", CollectorStatus.ERROR, data, f"{e}; repository file ignored"
                    )
                suppressions += from_repo
                data["repository"] = len(from_repo)
        return suppressions, CollectorResult("suppressions", CollectorStatus.OK, data, detail)

    def _synthesizer_node(self, state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
        runtime.context.emit("Synthesizing report")
        results = state["collector_results"]
        github = collector_data(results, "github_metadata") or {}
        layout = collector_data(results, "repo_layout") or {}
        languages = list((layout.get("lines_by_language") or {}).keys())
        repo = state["repo"]
        clone = collector_data(results, "repo_clone") or {}
        repository = {
            "name": github.get("name", repo.name),
            "full_name": github.get("full_name", repo.full_name),
            "url": github.get("url", repo.html_url),
            "description": github.get("description", ""),
            "language": github.get("language") or (languages[0] if languages else "Unknown"),
            "stars": github.get("stars", 0),
            "forks": github.get("forks", 0),
            "license": github.get("license_spdx_id"),
            # The exact code this report describes. `ref` is what was requested,
            # else the default branch (None if neither is known).
            "commit_sha": clone.get("commit_sha"),
            "ref": clone.get("ref") or github.get("default_branch"),
        }
        report = synthesize_report(
            repository=repository,
            category_findings=state["category_findings"],
            collector_status={
                n: {"status": r.status.value, "detail": r.detail} for n, r in results.items()
            },
            investigation_plan=state["investigation_plan"],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            drrepo_version=__version__,
            dependencies=dependency_inventory(collector_data(results, "dependency_audit")),
        )
        return {"report": report}

    # ---- graph -------------------------------------------------------------

    def _build_graph(self) -> Any:
        # Typed as Any: LangGraph's add_node overloads can't match closures over Runtime[...].
        graph: Any = StateGraph(State, context_schema=RunContext)
        depths = _depths(self.collectors)
        feeds_other = {p for spec in self.collectors for p in spec.after}

        for spec in self.collectors:
            graph.add_node(
                spec.name,
                self._collector_node(spec),
                defer=_needs_defer([depths[p] for p in spec.after]),
            )
            for predecessor in spec.after or (START,):
                graph.add_edge(predecessor, spec.name)

        leaves = [s.name for s in self.collectors if s.name not in feeds_other]
        graph.add_node(
            "planner", self._planner_node, defer=_needs_defer([depths[n] for n in leaves])
        )
        for name in leaves:
            graph.add_edge(name, "planner")

        # All category nodes sit one hop after the planner (symmetric), but the
        # synthesizer keeps defer=True as a guard; it has been verified safe.
        graph.add_node("synthesizer", self._synthesizer_node, defer=True)
        for category in self.analysts:
            node_name = f"{category.value}_review"
            graph.add_node(node_name, self._category_node(category))
            graph.add_edge("planner", node_name)
            graph.add_edge(node_name, "synthesizer")
        graph.add_edge("synthesizer", END)
        return graph.compile()

    # ---- entrypoint --------------------------------------------------------

    def run(
        self, repo: RepoRef, ctx: RunContext, description: str = "", ref: str | None = None
    ) -> dict[str, Any]:
        """Clone (at `ref`, or the default branch), run the graph, clean up.

        Returns `Report.to_dict()` (+ `llm_usage`).
        """
        ctx.emit(f"Cloning {repo.full_name}" + (f" at {ref}" if ref else ""))
        cloned, clone_result = clone_repo(repo.html_url, ctx.config, ref)
        if cloned:
            ctx.symbol_index = SymbolIndex(Path(cloned.path))
        suppressions, suppression_status = self._load_suppressions(
            ctx, cloned.path if cloned else None
        )
        initial: State = {
            "repo": repo,
            "description": description,
            "clone_path": str(cloned.path) if cloned else None,
            "suppressions": suppressions,
            "collector_results": {
                "repo_clone": clone_result,
                "suppressions": suppression_status,
            },
            "investigation_plan": InvestigationPlan.all_shallow("not planned yet"),
            "category_findings": {},
            "report": None,
        }
        try:
            final = self.graph.invoke(initial, context=ctx)
        finally:
            if cloned:
                cloned.cleanup()
        report: dict[str, Any] = final["report"].to_dict()
        report["provenance"] = build_provenance(ctx.config, llm_used=ctx.llm.available)
        if ctx.llm.budget is not None:
            estimate, source = ctx.deep_estimate()
            report["llm_usage"] = {
                **ctx.llm.budget.usage(),
                "deep_estimate": {"tokens": estimate, "source": source},
            }
        ctx.emit("Analysis complete")
        return report


def _suppressed_entries(result: SuppressionResult) -> list[dict[str, Any]]:
    return [{"issue": i.to_dict(), "suppression": s.to_dict()} for i, s in result.suppressed]


def recon_summary(results: Recon) -> dict[str, Any]:
    """Compact recon signals for the planner prompt (counts, not dumps)."""
    github = collector_data(results, "github_metadata") or {}
    layout = collector_data(results, "repo_layout") or {}
    readme = collector_data(results, "readme") or {}
    doc_checks = collector_data(results, "doc_checks")
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
        "broken_doc_links": len(doc_checks.get("broken_links", []))
        if doc_checks
        else "unavailable",
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
        "collector_status": {n: r.status.value for n, r in results.items()},
    }
