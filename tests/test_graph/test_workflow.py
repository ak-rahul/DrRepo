"""Integration-style test of the full workflow graph with everything mocked --
no network, no real LLM, no real git clone. Confirms the parallel
collectors -> analysts -> synthesizer graph actually wires together and
LangGraph's concurrent-write reducers work as expected."""

from unittest.mock import Mock, patch

from src.graph.workflow import Workflow
from src.models import (
    Category,
    CategoryPlan,
    CollectorResult,
    CollectorStatus,
    InvestigationDepth,
    InvestigationPlan,
)


def _ok(data=None, detail=None):
    return CollectorResult(name="x", status=CollectorStatus.OK, data=data or {}, detail=detail)


class TestWorkflowGraph:
    def test_graph_compiles(self, fake_config):
        with patch("src.graph.workflow.build_llm_client", return_value=Mock()):
            workflow = Workflow(fake_config)
        assert workflow.graph is not None

    @patch("src.graph.workflow.clone_repo")
    @patch("src.graph.workflow.collect_dependency_audit")
    @patch("src.graph.workflow.collect_security")
    @patch("src.graph.workflow.collect_static_analysis")
    @patch("src.graph.workflow.collect_github_metadata")
    def test_end_to_end_run_produces_report(
        self,
        mock_github,
        mock_static,
        mock_security,
        mock_dep,
        mock_clone,
        fake_config,
        sample_repo_data,
        mock_llm_response,
    ):
        mock_clone.return_value = (None, _ok(detail="skipped for test"))
        mock_github.return_value = _ok(data=sample_repo_data)
        mock_static.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_security.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_dep.return_value = _ok(data={"packages_checked": 0, "vulnerabilities": []})

        # This test is about the collectors->synthesizer wiring, not the v3
        # planner/investigator behavior (which has its own dedicated tests) --
        # force shallow so the fake LLM's unconfigured `.with_structured_output()`
        # Mock is never exercised.
        fake_config.enable_deep_investigation = False

        fake_llm = Mock()
        fake_llm.invoke = Mock(return_value=Mock(content=mock_llm_response))

        with patch("src.graph.workflow.build_llm_client", return_value=fake_llm):
            workflow = Workflow(fake_config)
            report = workflow.execute("https://github.com/user/test-repo")

        assert report["repository"]["name"] == "test-repo"
        assert "overall_score" in report
        assert set(report["category_scores"].keys()) == {
            "documentation",
            "code_quality",
            "security",
            "dependencies",
            "maintainability",
        }

    @patch("src.graph.workflow.clone_repo")
    @patch("src.graph.workflow.collect_dependency_audit")
    @patch("src.graph.workflow.collect_security")
    @patch("src.graph.workflow.collect_static_analysis")
    @patch("src.graph.workflow.collect_github_metadata")
    def test_clone_is_cleaned_up_after_run(
        self,
        mock_github,
        mock_static,
        mock_security,
        mock_dep,
        mock_clone,
        fake_config,
        sample_repo_data,
        mock_llm_response,
    ):
        fake_cloned = Mock()
        fake_cloned.path = "/tmp/fake"
        mock_clone.return_value = (fake_cloned, _ok(data={"path": "/tmp/fake", "size_mb": 1.0}))
        mock_github.return_value = _ok(data=sample_repo_data)
        mock_static.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_security.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_dep.return_value = _ok(data={"packages_checked": 0, "vulnerabilities": []})
        fake_config.enable_deep_investigation = False

        fake_llm = Mock()
        fake_llm.invoke = Mock(return_value=Mock(content=mock_llm_response))

        with patch("src.graph.workflow.build_llm_client", return_value=fake_llm):
            workflow = Workflow(fake_config)
            workflow.execute("https://github.com/user/test-repo")

        fake_cloned.cleanup.assert_called_once()

    @patch("src.graph.workflow.investigate")
    @patch("src.agents.planner.LeadInvestigator.plan")
    @patch("src.graph.workflow.clone_repo")
    @patch("src.graph.workflow.collect_dependency_audit")
    @patch("src.graph.workflow.collect_security")
    @patch("src.graph.workflow.collect_static_analysis")
    @patch("src.graph.workflow.collect_github_metadata")
    def test_planner_routes_only_flagged_categories_to_deep_investigation(
        self,
        mock_github,
        mock_static,
        mock_security,
        mock_dep,
        mock_clone,
        mock_plan,
        mock_investigate,
        fake_config,
        sample_repo_data,
        mock_llm_response,
    ):
        """The genuinely-agentic part: only the category the planner marks
        'deep' should go through the tool-calling investigator; everything
        else stays on the fast single-call path."""
        fake_cloned = Mock()
        fake_cloned.path = "/tmp/fake-clone"
        mock_clone.return_value = (
            fake_cloned,
            _ok(data={"path": "/tmp/fake-clone", "size_mb": 1.0}),
        )
        mock_github.return_value = _ok(data=sample_repo_data)
        mock_static.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_security.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_dep.return_value = _ok(data={"packages_checked": 0, "vulnerabilities": []})

        mock_plan.return_value = InvestigationPlan(
            plans={
                Category.SECURITY.value: CategoryPlan(
                    category=Category.SECURITY, depth=InvestigationDepth.DEEP, rationale="test"
                ),
                **{
                    c.value: CategoryPlan(
                        category=c, depth=InvestigationDepth.SHALLOW, rationale="test"
                    )
                    for c in Category
                    if c != Category.SECURITY
                },
            }
        )
        mock_investigate.return_value = {
            "summary": "deep dive result",
            "score": 42.0,
            "issues": [],
            "investigation_depth": "deep",
            "investigation_trace": [
                {"tool": "read_file", "tool_input": {"path": "x"}, "observation": "y"}
            ],
        }

        fake_llm = Mock()
        fake_llm.invoke = Mock(return_value=Mock(content=mock_llm_response))

        with patch("src.graph.workflow.build_llm_client", return_value=fake_llm):
            workflow = Workflow(fake_config)
            report = workflow.execute("https://github.com/user/test-repo")

        mock_investigate.assert_called_once()
        _, call_kwargs = mock_investigate.call_args
        assert call_kwargs["category"] == Category.SECURITY

        security_score = report["category_scores"]["security"]
        assert security_score["investigation_depth"] == "deep"
        assert security_score["score"] == 42.0
        assert report["category_scores"]["documentation"]["investigation_depth"] == "shallow"

    @patch("src.graph.workflow.investigate")
    @patch("src.agents.planner.LeadInvestigator.plan")
    @patch("src.graph.workflow.clone_repo")
    @patch("src.graph.workflow.collect_dependency_audit")
    @patch("src.graph.workflow.collect_security")
    @patch("src.graph.workflow.collect_static_analysis")
    @patch("src.graph.workflow.collect_github_metadata")
    def test_disabling_deep_investigation_forces_all_shallow_and_skips_planner_llm_call(
        self,
        mock_github,
        mock_static,
        mock_security,
        mock_dep,
        mock_clone,
        mock_plan,
        mock_investigate,
        fake_config,
        sample_repo_data,
        mock_llm_response,
    ):
        """The ENABLE_DEEP_INVESTIGATION=false kill switch must reproduce the
        old all-shallow behavior exactly, including never spending an LLM
        call on planning -- a regression safety net and a cost control."""
        fake_cloned = Mock()
        fake_cloned.path = "/tmp/fake-clone"
        mock_clone.return_value = (
            fake_cloned,
            _ok(data={"path": "/tmp/fake-clone", "size_mb": 1.0}),
        )
        mock_github.return_value = _ok(data=sample_repo_data)
        mock_static.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_security.return_value = _ok(data={"findings": [], "tool_status": {}})
        mock_dep.return_value = _ok(data={"packages_checked": 0, "vulnerabilities": []})

        # Even if the planner *would* say "deep", the kill switch must never
        # let that plan reach the router -- prove this by making the (unused)
        # mocked plan say everything should go deep.
        mock_plan.return_value = InvestigationPlan(
            plans={
                c.value: CategoryPlan(category=c, depth=InvestigationDepth.DEEP, rationale="x")
                for c in Category
            }
        )
        fake_config.enable_deep_investigation = False

        fake_llm = Mock()
        fake_llm.invoke = Mock(return_value=Mock(content=mock_llm_response))

        with patch("src.graph.workflow.build_llm_client", return_value=fake_llm):
            workflow = Workflow(fake_config)
            report = workflow.execute("https://github.com/user/test-repo")

        mock_plan.assert_not_called()
        mock_investigate.assert_not_called()
        for cs in report["category_scores"].values():
            assert cs["investigation_depth"] == "shallow"
            assert cs["investigation_trace"] == []
