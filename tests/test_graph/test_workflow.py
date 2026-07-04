"""Integration-style test of the full workflow graph with everything mocked --
no network, no real LLM, no real git clone. Confirms the parallel
collectors -> analysts -> synthesizer graph actually wires together and
LangGraph's concurrent-write reducers work as expected."""

from unittest.mock import Mock, patch

from src.graph.workflow import Workflow
from src.models import CollectorResult, CollectorStatus


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

        fake_llm = Mock()
        fake_llm.invoke = Mock(return_value=Mock(content=mock_llm_response))

        with patch("src.graph.workflow.build_llm_client", return_value=fake_llm):
            workflow = Workflow(fake_config)
            workflow.execute("https://github.com/user/test-repo")

        fake_cloned.cleanup.assert_called_once()
