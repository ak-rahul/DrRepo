"""Full graph runs with collectors, clone, and LLM mocked: no network, no git."""

import threading
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from drrepo.agents.investigator import InvestigationResult
from drrepo.agents.llm import LLMRuntime, TokenBudget
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
    calls: Counter = Counter()
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
    assert lead.return_value.plan.call_args.args[1] == 2  # 25k // 12k


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
