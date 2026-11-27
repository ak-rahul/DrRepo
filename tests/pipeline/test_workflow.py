"""Full graph runs with collectors, clone, and LLM mocked: no network, no git."""

from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from drrepo.agents.investigator import InvestigationError, InvestigationResult
from drrepo.config import Config
from drrepo.core.budget import LLMBudgetTracker
from drrepo.core.circuit_breaker import CircuitBreaker
from drrepo.models import (
    Category,
    CategoryPlan,
    CollectorResult,
    CollectorStatus,
    InvestigationDepth,
    InvestigationPlan,
    Issue,
    Location,
    Severity,
    ToolCallTrace,
)
from drrepo.pipeline.workflow import Workflow

W = "drrepo.pipeline.workflow"


def _ok(name, data):
    return CollectorResult(name=name, status=CollectorStatus.OK, data=data)


@pytest.fixture
def collectors(github_data, tmp_path):
    """Patch every collector + clone; yields a Counter of how often each ran."""
    calls: Counter = Counter()
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    cloned = MagicMock(path=clone_dir)

    def track(name, result):
        def fn(*_a, **_k):
            calls[name] += 1
            return result

        return fn

    patches = [
        patch(f"{W}.clone_repo", side_effect=track("clone", (cloned, _ok("repo_clone", {})))),
        patch(
            f"{W}.collect_github_metadata",
            side_effect=track("github", _ok("github_metadata", github_data)),
        ),
        patch(
            f"{W}.collect_repo_layout",
            side_effect=track(
                "layout",
                _ok(
                    "repo_layout",
                    {
                        "file_structure": {"has_tests": True, "has_ci": True, "has_license": True},
                        "python_lines": 2000,
                    },
                ),
            ),
        ),
        patch(
            f"{W}.collect_static_analysis",
            side_effect=track(
                "static",
                _ok(
                    "static_analysis",
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
                    },
                ),
            ),
        ),
        patch(
            f"{W}.collect_security",
            side_effect=track(
                "security", _ok("security", {"findings": [], "tool_status": {"bandit": "ok"}})
            ),
        ),
        patch(
            f"{W}.collect_dependency_audit",
            side_effect=track(
                "deps",
                _ok(
                    "dependency_audit",
                    {
                        "packages_checked": 3,
                        "vulnerabilities": [],
                        "manifests": ["uv.lock"],
                        "unpinned": [],
                    },
                ),
            ),
        ),
    ]
    for p in patches:
        p.start()
    yield {"calls": calls, "cloned": cloned}
    for p in patches:
        p.stop()


def _workflow(config=None, client=None, **kwargs):
    client = client or MagicMock()
    client.invoke.return_value = MagicMock(content="narrative", usage_metadata={"total_tokens": 10})
    return Workflow(config or Config(groq_api_key="k"), llm_client=client, **kwargs)


def test_end_to_end_shallow(collectors):
    workflow = _workflow(Config(groq_api_key="k", enable_deep_investigation=False))
    progress: list[str] = []
    report = workflow.execute("https://github.com/octo/demo.git", progress=progress.append)

    assert report["repository"]["full_name"] == "octo/demo"
    assert set(report["category_scores"]) == {c.value for c in Category}
    assert report["category_scores"]["code_quality"]["issues"][0]["severity"] == "high"
    assert report["category_scores"]["security"]["summary"]  # LLM not needed for clean category
    assert all(cs["investigation_depth"] == "shallow" for cs in report["category_scores"].values())
    assert (
        report["investigation_plan"]["security"]["rationale"]
        == "deep investigation disabled by config"
    )
    assert "llm_usage" in report and report["drrepo_version"]
    assert progress[0] == "Cloning octo/demo" and progress[-1] == "Analysis complete"
    collectors["cloned"].cleanup.assert_called_once()


def test_every_node_runs_exactly_once(collectors):
    """Regression: a deferred node feeding another deferred node made every category run twice."""
    workflow = _workflow(Config(groq_api_key="k", enable_deep_investigation=False))
    with patch.object(workflow, "run_category", wraps=workflow.run_category) as run_category:
        workflow.execute("https://github.com/octo/demo")
    assert Counter(call.args[1] for call in run_category.call_args_list) == Counter(set(Category))
    assert all(n == 1 for n in collectors["calls"].values())


def test_cleanup_even_when_graph_fails(collectors):
    workflow = _workflow(Config(groq_api_key="k", enable_deep_investigation=False))
    with patch.object(workflow, "_synthesizer_node", side_effect=RuntimeError("boom")):
        workflow.graph = workflow._build_graph()
        with pytest.raises(RuntimeError):
            workflow.execute("https://github.com/octo/demo")
    collectors["cloned"].cleanup.assert_called_once()


def test_invalid_url_raises_before_cloning(collectors):
    with pytest.raises(ValueError):
        _workflow().execute("https://example.com/x")
    assert collectors["calls"]["clone"] == 0


def test_no_llm_configured_is_fully_deterministic(collectors):
    workflow = Workflow(Config(groq_api_key=""))  # no key, no client
    assert workflow.llm.available is False
    report = workflow.execute("https://github.com/octo/demo")
    assert report["investigation_plan"]["security"]["rationale"] == "no LLM provider configured"
    assert report["overall_score"] > 0


def _plan(*deep):
    return InvestigationPlan(
        plans={
            c.value: CategoryPlan(
                c, InvestigationDepth.DEEP if c in deep else InvestigationDepth.SHALLOW, "r"
            )
            for c in Category
        }
    )


def test_deep_merges_investigator_issues_and_rescores(collectors):
    workflow = _workflow()
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
        patch.object(workflow.lead_investigator, "plan", return_value=_plan(Category.CODE_QUALITY)),
        patch(f"{W}.investigate", return_value=result) as inv,
    ):
        report = workflow.execute("https://github.com/octo/demo")

    cq = report["category_scores"]["code_quality"]
    assert cq["investigation_depth"] == "deep" and cq["summary"] == "deep summary"
    assert {i["title"] for i in cq["issues"]} >= {"Swallowed exception"}
    assert any(i["source"] == "ruff" for i in cq["issues"])  # recon findings kept
    assert cq["investigation_trace"][0]["tool"] == "read_file"
    tool_names = {t.name for t in inv.call_args.kwargs["tools"]}
    assert {"read_file", "run_scanner_on_path"} <= tool_names
    assert inv.call_args.kwargs["known_issues"]  # recon issues passed so they aren't repeated

    shallow_score = _workflow(Config(groq_api_key="k", enable_deep_investigation=False)).execute(
        "https://github.com/octo/demo"
    )
    assert cq["score"] < shallow_score["category_scores"]["code_quality"]["score"]


def test_deep_failure_falls_back_to_shallow_with_note(collectors):
    workflow = _workflow()
    with (
        patch.object(workflow.lead_investigator, "plan", return_value=_plan(Category.SECURITY)),
        patch(
            f"{W}.investigate",
            side_effect=InvestigationError("reached its 8-tool-call budget before concluding"),
        ),
    ):
        report = workflow.execute("https://github.com/octo/demo")
    security = report["category_scores"]["security"]
    assert security["investigation_depth"] == "shallow"
    assert "tool-call budget" in security["notes"][-1]


def test_budget_caps_deep_count_and_resets_per_run(collectors):
    budget = LLMBudgetTracker(25_000)
    config = Config(groq_api_key="k", estimated_tokens_per_deep_investigation=12_000)
    workflow = _workflow(config, llm_budget=budget)
    seen_caps = []

    def plan(summary, max_deep, user_context=""):
        seen_caps.append(max_deep)
        return InvestigationPlan.all_shallow("x")

    with patch.object(workflow.lead_investigator, "plan", side_effect=plan):
        workflow.execute("https://github.com/octo/demo")
        workflow.execute("https://github.com/octo/demo")
    assert seen_caps == [2, 2]  # fresh budget each run, despite the first run's spending


def test_shared_breaker_open_degrades_gracefully(collectors):
    """Parallel nodes already in flight can each fail once, but once the shared breaker
    is open, every later LLM call -- including the whole next run -- short-circuits."""
    breaker = CircuitBreaker(failure_threshold=1, timeout=600)
    client = MagicMock()
    client.invoke.side_effect = ConnectionError("quota exhausted")
    config = Config(groq_api_key="k", enable_deep_investigation=False)
    with patch("drrepo.core.retry.time.sleep"):
        report = Workflow(config, llm_client=client, llm_breaker=breaker).execute(
            "https://github.com/octo/demo"
        )
        assert breaker.get_state()["state"] == "open"
        assert any(cs["notes"] for cs in report["category_scores"].values())
        assert report["overall_score"] > 0  # deterministic results survive

        calls_after_first_run = client.invoke.call_count
        second = Workflow(config, llm_client=client, llm_breaker=breaker).execute(
            "https://github.com/octo/demo"
        )
    assert client.invoke.call_count == calls_after_first_run  # nothing reached the provider
    assert any(
        "CircuitOpenError" in n for cs in second["category_scores"].values() for n in cs["notes"]
    )


def test_readme_falls_back_to_clone(collectors, github_data):
    workflow = _workflow(Config(groq_api_key="k", enable_deep_investigation=False))
    failed = CollectorResult(
        name="github_metadata", status=CollectorStatus.ERROR, detail="rate limited"
    )
    layout = _ok(
        "repo_layout", {"file_structure": {}, "readme_content": "# From clone\n\n## Usage\n"}
    )
    with (
        patch(f"{W}.collect_github_metadata", return_value=failed),
        patch(f"{W}.collect_repo_layout", return_value=layout),
    ):
        report = workflow.execute("https://github.com/octo/demo")
    assert report["category_scores"]["documentation"]["assessed"] is True
    assert report["repository"]["name"] == "demo"  # fallback from the URL


def test_recon_summary_counts(collectors):
    workflow = _workflow(Config(groq_api_key="k", enable_deep_investigation=False))
    state = {
        "collector_results": {
            "security": {
                "status": "ok",
                "data": {
                    "findings": [
                        {"tool": "secret_scan", "severity": "CRITICAL"},
                        {"tool": "bandit", "severity": "LOW"},
                    ]
                },
            },
            "static_analysis": {"status": "skipped", "data": {}},
        }
    }
    summary = workflow.recon_summary(state)  # type: ignore[arg-type]
    assert summary["possible_secrets"] == 1 and summary["high_severity_security_findings"] == 1
    assert summary["static_analysis_findings"] == "unavailable"
