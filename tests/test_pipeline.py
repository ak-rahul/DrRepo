"""Full graph runs with collectors, clone, and LLM mocked: no network, no git."""

import threading
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from drrepo.agents.investigator import InvestigationResult
from drrepo.agents.llm import LLMRuntime, TokenBudget
from drrepo.agents.tool_server import ToolServerError
from drrepo.config import Config
from drrepo.errors import InvestigationError
from drrepo.models import (
    Category,
    CategoryPlan,
    CollectorResult,
    InvestigationDepth,
    InvestigationPlan,
    Issue,
    Location,
    RepoRef,
    Severity,
    ToolCallTrace,
)
from drrepo.pipeline import COLLECTORS, RunContext, Workflow, _depths, _needs_defer, recon_summary
from drrepo.resilience import CircuitBreaker
from tests.conftest import failed, ok

P = "drrepo.pipeline"
REPO = RepoRef("octo", "demo")


@pytest.fixture
def collectors(github_data, tmp_path):
    """Patch clone + every collector; yields call counts and the fake clone."""
    calls: Counter[str] = Counter()
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    cloned = MagicMock(path=clone_dir)

    def track(name, result):
        def fn(*_a, **_k):
            calls[name] += 1
            return result

        return fn

    results = {
        "clone_repo": (cloned, ok(name="repo_clone")),
        "collect_github_metadata": ok(github_data),
        "collect_repo_layout": ok(
            {
                "file_structure": {"has_tests": True, "has_ci": True, "has_license": True},
                "python_lines": 2000,
            }
        ),
        "collect_static_analysis": ok(
            {
                "findings": [
                    {
                        "tool": "ruff",
                        "rule": "F821",
                        "message": "undefined",
                        "file": "a.py",
                        "line": 1,
                    }
                ]
            }
        ),
        "collect_security": ok({"findings": [], "tool_status": {"bandit": "ok"}}),
        "collect_dependency_audit": ok(
            {"packages_checked": 3, "vulnerabilities": [], "manifests": ["uv.lock"], "unpinned": []}
        ),
    }
    patches = [
        patch(f"{P}.{name}", side_effect=track(name, result)) for name, result in results.items()
    ]
    for p in patches:
        p.start()
    yield {"calls": calls, "cloned": cloned}
    for p in patches:
        p.stop()


def _client():
    client = MagicMock()
    client.invoke.return_value = MagicMock(content="narrative", usage_metadata={"total_tokens": 10})
    return client


def _ctx(config=None, client="default", budget=None, breaker=None, progress=None):
    ctx = RunContext(
        config=config or Config(groq_api_key="k"),
        llm=LLMRuntime(
            client=_client() if client == "default" else client, breaker=breaker, budget=budget
        ),
    )
    if progress:
        ctx.progress = progress
    return ctx


SHALLOW = Config(groq_api_key="k", enable_deep_investigation=False)


def _plan(*deep):
    return InvestigationPlan(
        plans={
            c.value: CategoryPlan(
                c, InvestigationDepth.DEEP if c in deep else InvestigationDepth.SHALLOW, "r"
            )
            for c in Category
        }
    )


def test_end_to_end_shallow(collectors):
    progress: list[str] = []
    report = Workflow().run(REPO, _ctx(SHALLOW, budget=TokenBudget(1000), progress=progress.append))

    assert report["repository"]["full_name"] == "octo/demo"
    assert set(report["category_scores"]) == {c.value for c in Category}
    assert report["category_scores"]["code_quality"]["issues"][0]["severity"] == "high"
    assert all(cs["investigation_depth"] == "shallow" for cs in report["category_scores"].values())
    assert (
        report["investigation_plan"]["security"]["rationale"]
        == "deep investigation disabled by config"
    )
    assert report["collector_status"]["readme"]["status"] == "ok"
    assert "llm_usage" in report and report["drrepo_version"]
    assert progress[0] == "Cloning octo/demo" and progress[-1] == "Analysis complete"
    collectors["cloned"].cleanup.assert_called_once()


def test_every_node_runs_exactly_once(collectors):
    """Regression: a deferred node feeding another deferred node made every category run twice."""
    workflow = Workflow()
    with patch.object(workflow, "analyze_category", wraps=workflow.analyze_category) as analyze:
        workflow.run(REPO, _ctx(SHALLOW))
    assert Counter(call.args[0] for call in analyze.call_args_list) == Counter(set(Category))
    assert all(n == 1 for n in collectors["calls"].values())


def test_defer_is_derived_from_topology():
    depths = _depths(COLLECTORS)
    assert depths["readme"] == 2 and depths["security"] == 1
    assert not _needs_defer([depths["github_metadata"], depths["repo_layout"]])  # readme: symmetric
    assert _needs_defer([1, 1, 2])  # planner: readme is one level deeper


def test_one_compiled_graph_serves_concurrent_runs(collectors):
    workflow = Workflow()
    seen: dict[str, list[str]] = {"a": [], "b": []}
    errors: list[BaseException] = []

    def run(tag):
        try:
            workflow.run(REPO, _ctx(SHALLOW, progress=seen[tag].append))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=run, args=(t,)) for t in seen]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    # Each run's progress went only to its own callback.
    assert seen["a"].count("Analysis complete") == 1 and seen["b"].count("Analysis complete") == 1


def test_cleanup_even_when_graph_fails(collectors):
    workflow = Workflow()
    with (
        patch(f"{P}.synthesize_report", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        workflow.run(REPO, _ctx(SHALLOW))
    collectors["cloned"].cleanup.assert_called_once()


def test_no_clone_skips_clone_collectors_uniformly(collectors):
    with patch(f"{P}.clone_repo", return_value=(None, failed("private", name="repo_clone"))):
        report = Workflow().run(REPO, _ctx(SHALLOW))
    status = report["collector_status"]
    assert {
        status[n]["detail"]
        for n in ("repo_layout", "static_analysis", "security", "dependency_audit")
    } == {"no clone"}
    assert collectors["calls"]["collect_static_analysis"] == 0
    assert report["category_scores"]["code_quality"]["assessed"] is False


def test_no_llm_is_fully_deterministic(collectors):
    report = Workflow().run(REPO, _ctx(Config(), client=None))
    assert report["investigation_plan"]["security"]["rationale"] == "no LLM provider configured"
    assert report["overall_score"] > 0


def test_deep_merges_investigator_issues_and_rescores(collectors):
    (collectors["cloned"].path / "b.py").write_text("x = 1\n" * 20, encoding="utf-8")
    workflow = Workflow()
    extra = Issue(
        Severity.HIGH,
        Category.CODE_QUALITY,
        "Swallowed exception",
        "d",
        "r",
        "investigator:code_quality",
        locations=[Location("b.py", 9)],
    )
    result = InvestigationResult(
        summary="deep summary",
        issues=[extra],
        trace=[ToolCallTrace("read_file", {"path": "b.py"}, "obs")],
    )
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", return_value=result) as inv,
    ):
        lead.return_value.plan.return_value = _plan(Category.CODE_QUALITY)
        report = workflow.run(REPO, _ctx(budget=TokenBudget(100_000)))

    cq = report["category_scores"]["code_quality"]
    assert cq["investigation_depth"] == "deep" and cq["summary"] == "deep summary"
    assert {i["source"] for i in cq["issues"]} == {
        "ruff",
        "investigator:code_quality",
    }  # recon kept
    assert cq["investigation_trace"][0]["tool"] == "read_file"
    kwargs = inv.call_args.kwargs
    assert {"read_file", "run_scanner_on_path"} <= {t.name for t in kwargs["tools"]}
    assert kwargs["known_issues"]  # recon issues passed so they aren't repeated

    shallow = Workflow().run(REPO, _ctx(SHALLOW))
    assert cq["score"] < shallow["category_scores"]["code_quality"]["score"]


def test_deep_failure_falls_back_to_shallow_with_note(collectors):
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(
            f"{P}.investigate",
            side_effect=InvestigationError("reached its 8-tool-call budget before concluding"),
        ),
    ):
        lead.return_value.plan.return_value = _plan(Category.SECURITY)
        report = Workflow().run(REPO, _ctx())
    security = report["category_scores"]["security"]
    assert security["investigation_depth"] == "shallow"
    assert "tool-call budget" in security["notes"][-1]


def test_budget_caps_deep_count(collectors):
    config = Config(groq_api_key="k", estimated_tokens_per_deep_investigation=12_000)
    with patch(f"{P}.LeadInvestigator") as lead:
        lead.return_value.plan.return_value = InvestigationPlan.all_shallow("x")
        Workflow().run(REPO, _ctx(config, budget=TokenBudget(25_000)))
    assert lead.return_value.plan.call_args.args[1] == 4  # units of half a deep run: 25k // 6k


def test_measured_cost_sizes_the_budget(collectors):
    config = Config(groq_api_key="k", estimated_tokens_per_deep_investigation=12_000)
    ctx = _ctx(config, budget=TokenBudget(25_000))
    ctx.deep_investigation_tokens = 5_000  # history says deep runs are cheap here
    with patch(f"{P}.LeadInvestigator") as lead:
        lead.return_value.plan.return_value = InvestigationPlan.all_shallow("x")
        report = Workflow().run(REPO, ctx)
    assert lead.return_value.plan.call_args.args[1] == 10  # 25k // 2.5k, capped at 5 deep
    assert report["llm_usage"]["deep_estimate"] == {"tokens": 5_000, "source": "history"}


def test_open_breaker_short_circuits_later_runs(collectors):
    """In-flight parallel calls may each fail once, but once the shared breaker is
    open, every later LLM call -- including the whole next run -- short-circuits."""
    breaker = CircuitBreaker(failure_threshold=1, timeout=600)
    client = MagicMock()
    client.invoke.side_effect = ConnectionError("quota exhausted")
    workflow = Workflow()
    with patch("drrepo.resilience.time.sleep"):
        first = workflow.run(REPO, _ctx(SHALLOW, client=client, breaker=breaker))
        assert breaker.get_state()["state"] == "open"
        assert first["overall_score"] > 0
        calls = client.invoke.call_count
        second = workflow.run(REPO, _ctx(SHALLOW, client=client, breaker=breaker))
    assert client.invoke.call_count == calls
    assert any(
        "CircuitOpenError" in n for cs in second["category_scores"].values() for n in cs["notes"]
    )


def test_readme_falls_back_to_clone(collectors):
    layout = ok({"file_structure": {}, "readme_content": "# From clone\n\n## Usage\n"})
    with (
        patch(f"{P}.collect_github_metadata", return_value=failed("rate limited")),
        patch(f"{P}.collect_repo_layout", return_value=layout),
    ):
        report = Workflow().run(REPO, _ctx(SHALLOW))
    assert report["category_scores"]["documentation"]["assessed"] is True
    assert report["repository"]["name"] == "demo"  # from the RepoRef


def test_readme_comes_from_the_analyzed_commit_not_the_api(github_data):
    """The GitHub API serves HEAD's README; a pinned analysis must read the clone's."""
    from drrepo.pipeline import _readme

    def state(layout_readme):
        return {
            "collector_results": {
                "github_metadata": ok({**github_data, "readme_content": "# HEAD\n"}),
                "repo_layout": ok({"readme_content": layout_readme}),
            }
        }

    pinned = _readme(state("# Pinned\n\n## Installation\n\n## Usage\n"), None)  # type: ignore[arg-type]
    assert pinned.data["section_count"] == 3
    api_fallback = _readme(state(""), None)  # type: ignore[arg-type]
    assert api_fallback.data["section_count"] == 1  # the clone had no README


def test_recon_summary_counts():
    results = {
        "security": ok(
            {
                "findings": [
                    {"tool": "secret_scan", "severity": "CRITICAL"},
                    {"tool": "bandit", "severity": "LOW"},
                ]
            }
        ),
        "static_analysis": CollectorResult.skipped("static_analysis", "no clone"),
    }
    summary = recon_summary(results)
    assert summary["possible_secrets"] == 1 and summary["high_severity_security_findings"] == 1
    assert summary["static_analysis_findings"] == "unavailable"


def test_report_records_the_analyzed_commit(collectors):
    with patch(
        f"{P}.clone_repo",
        return_value=(
            collectors["cloned"],
            ok({"commit_sha": "d" * 40, "ref": "v2"}, name="repo_clone"),
        ),
    ):
        report = Workflow().run(REPO, _ctx(SHALLOW), ref="v2")
    assert report["repository"]["commit_sha"] == "d" * 40
    assert report["repository"]["ref"] == "v2"


def test_fabricated_agent_findings_are_dropped_and_noted(collectors):
    """End to end: a finding that cites a file the clone doesn't have never reaches the report."""
    (collectors["cloned"].path / "real.py").write_text("print(1)\n", encoding="utf-8")
    fabricated = Issue(
        Severity.CRITICAL,
        Category.SECURITY,
        "Hardcoded key",
        "d",
        "r",
        "investigator:security",
        locations=[Location("does/not/exist.py", 3)],
    )
    unread = Issue(
        Severity.HIGH,
        Category.SECURITY,
        "Weak hash",
        "d",
        "r",
        "investigator:security",
        locations=[Location("real.py", 1)],
    )
    result = InvestigationResult(summary="s", issues=[fabricated, unread], trace=[])
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", return_value=result),
    ):
        lead.return_value.plan.return_value = _plan(Category.SECURITY)
        report = Workflow().run(REPO, _ctx(budget=TokenBudget(100_000)))

    security = report["category_scores"]["security"]
    titles = {i["title"]: i["severity"] for i in security["issues"]}
    assert "Hardcoded key" not in titles
    assert titles["[unverified] Weak hash"] == "low"
    assert any(n.startswith("Grounding check:") for n in security["notes"])


def test_a_crashing_collector_degrades_instead_of_failing_the_run(collectors):
    with patch(f"{P}.collect_security", side_effect=KeyError("boom")):
        report = Workflow().run(REPO, _ctx(SHALLOW))
    status = report["collector_status"]["security"]
    assert status["status"] == "error" and "KeyError" in status["detail"]
    assert report["category_scores"]["security"]["assessed"] is False
    assert report["category_scores"]["code_quality"]["assessed"] is True  # the rest carried on


def test_lite_investigation_gets_half_the_tool_calls(collectors):
    plan = _plan()
    plan.plans["security"] = CategoryPlan(Category.SECURITY, InvestigationDepth.LITE, "borderline")
    result = InvestigationResult(summary="lite summary", issues=[], trace=[])
    config = Config(groq_api_key="k", max_tool_calls_per_investigator=8)
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", return_value=result) as inv,
    ):
        lead.return_value.plan.return_value = plan
        report = Workflow().run(REPO, _ctx(config, budget=TokenBudget(100_000)))
    assert inv.call_args.kwargs["max_tool_calls"] == 4
    assert inv.call_args.kwargs["llm"].label == "investigation:security"
    assert report["category_scores"]["security"]["investigation_depth"] == "lite"


def test_critic_can_be_turned_off(collectors):
    (collectors["cloned"].path / "b.py").write_text("x = 1\n" * 20, encoding="utf-8")
    severe = Issue(
        Severity.CRITICAL,
        Category.SECURITY,
        "Remote code execution",
        "d",
        "r",
        "investigator:security",
        locations=[Location("b.py", 3)],
    )
    result = InvestigationResult(
        summary="s", issues=[severe], trace=[ToolCallTrace("read_file", {"path": "b.py"}, "obs")]
    )
    config = Config(groq_api_key="k", enable_agent_critic=False)
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", return_value=result),
        patch(f"{P}.critic_review") as critic,
    ):
        lead.return_value.plan.return_value = _plan(Category.SECURITY)
        report = Workflow().run(REPO, _ctx(config, budget=TokenBudget(100_000)))
    critic.assert_not_called()
    titles = {i["title"]: i["severity"] for i in report["category_scores"]["security"]["issues"]}
    assert titles["Remote code execution"] == "critical"


def test_an_empty_deep_allowance_skips_planning(collectors):
    ctx = _ctx(budget=TokenBudget(100_000))
    ctx.deep_allowed = frozenset()
    with patch(f"{P}.LeadInvestigator") as lead:
        report = Workflow().run(REPO, ctx)
    lead.assert_not_called()
    assert report["investigation_plan"]["security"]["rationale"] == (
        "no category changed since the base commit"
    )


def test_pipeline_falls_back_to_in_process_tools(collectors):

    (collectors["cloned"].path / "b.py").write_text("x = 1\n" * 20, encoding="utf-8")
    issue = Issue(
        Severity.MEDIUM,
        Category.CODE_QUALITY,
        "Swallowed exception",
        "d",
        "r",
        "investigator:code_quality",
        locations=[Location("b.py", 9)],
    )
    result = InvestigationResult(
        summary="s", issues=[issue], trace=[ToolCallTrace("read_file", {"path": "b.py"}, "obs")]
    )
    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", return_value=result) as inv,
        patch(f"{P}.mcp_tools", side_effect=ToolServerError("MCP tool server unavailable: boom")),
    ):
        lead.return_value.plan.return_value = _plan(Category.CODE_QUALITY)
        report = Workflow().run(REPO, _ctx(budget=TokenBudget(100_000)))
    cq = report["category_scores"]["code_quality"]
    assert any("used in-process tools" in n for n in cq["notes"])
    assert {t.name for t in inv.call_args.kwargs["tools"]} >= {"read_file", "find_definition"}
    assert cq["investigation_depth"] == "deep"


def test_pipeline_uses_mcp_tools_by_default(collectors):

    seen = {}

    def fake_investigate(**kwargs):
        tool = {t.name: t for t in kwargs["tools"]}["list_directory"]
        seen["listing"] = tool.invoke({"path": "."})
        seen["type"] = type(tool).__name__
        return InvestigationResult(summary="s", issues=[], trace=[])

    with (
        patch(f"{P}.LeadInvestigator") as lead,
        patch(f"{P}.investigate", side_effect=fake_investigate),
    ):
        lead.return_value.plan.return_value = _plan(Category.SECURITY)
        Workflow().run(REPO, _ctx(budget=TokenBudget(100_000)))
    assert seen["type"] == "StructuredTool" and "ERROR" not in seen["listing"]
