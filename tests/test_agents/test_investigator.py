"""Tests for the tool-calling investigator agent wrapper.

`create_agent`'s internals are LangChain's responsibility (verified live
against the real Groq API during development -- see CLAUDE.md). These tests
mock `create_agent` itself and feed it realistic message objects, so they
verify *our* wrapper logic (trace extraction, severity normalization, score
clamping, recursion-limit handling) deterministically and without needing a
fake model that implements real tool-calling/bind_tools support.
"""

from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from src.agents.investigator import (
    InvestigationOutput,
    IssueOutput,
    investigate,
    summarize_recon_data,
)
from src.models import Category
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker


def _agent_returning(messages, structured_response):
    mock_agent = Mock()
    mock_agent.invoke = Mock(
        return_value={"messages": messages, "structured_response": structured_response}
    )
    return mock_agent


class TestInvestigate:
    @patch("src.agents.investigator.create_agent")
    def test_extracts_trace_from_tool_calls(self, mock_create_agent):
        messages = [
            HumanMessage(content="investigate"),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "app.py"}, "id": "c1"}],
            ),
            ToolMessage(content="import os\npassword = 'x'", tool_call_id="c1"),
            AIMessage(content="done"),
        ]
        structured = InvestigationOutput(summary="found a secret", score=40.0, issues=[])
        mock_create_agent.return_value = _agent_returning(messages, structured)

        result = investigate(
            category=Category.SECURITY,
            system_prompt="investigate security",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert result["investigation_depth"] == "deep"
        assert len(result["investigation_trace"]) == 1
        assert result["investigation_trace"][0]["tool"] == "read_file"
        assert result["investigation_trace"][0]["tool_input"] == {"path": "app.py"}
        assert "password" in result["investigation_trace"][0]["observation"]

    @patch("src.agents.investigator.create_agent")
    def test_structured_output_submission_excluded_from_trace(self, mock_create_agent):
        """`create_agent` submits the final answer as a synthetic tool call
        named after the response_format class (confirmed live against Groq:
        a call named "InvestigationOutput" appears once per run) -- that's
        the agent answering, not investigating, so it must not show up in
        the "how it investigated this" trace."""
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "app.py"}, "id": "c1"}],
            ),
            ToolMessage(content="file contents", tool_call_id="c1"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "InvestigationOutput",
                        "args": {"summary": "s", "score": 100.0, "issues": []},
                        "id": "c2",
                    }
                ],
            ),
        ]
        structured = InvestigationOutput(summary="s", score=100.0, issues=[])
        mock_create_agent.return_value = _agent_returning(messages, structured)

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert len(result["investigation_trace"]) == 1
        assert result["investigation_trace"][0]["tool"] == "read_file"

    @patch("src.agents.investigator.create_agent")
    def test_multiple_tool_calls_in_one_ai_message_all_traced(self, mock_create_agent):
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read_file", "args": {"path": "a.py"}, "id": "c1"},
                    {"name": "read_file", "args": {"path": "b.py"}, "id": "c2"},
                ],
            ),
            ToolMessage(content="content a", tool_call_id="c1"),
            ToolMessage(content="content b", tool_call_id="c2"),
        ]
        structured = InvestigationOutput(summary="s", score=100.0, issues=[])
        mock_create_agent.return_value = _agent_returning(messages, structured)

        result = investigate(
            category=Category.CODE_QUALITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert len(result["investigation_trace"]) == 2
        paths = {t["tool_input"]["path"] for t in result["investigation_trace"]}
        assert paths == {"a.py", "b.py"}

    @patch("src.agents.investigator.create_agent")
    def test_issues_get_category_and_source_tagged(self, mock_create_agent):
        structured = InvestigationOutput(
            summary="s",
            score=50.0,
            issues=[
                IssueOutput(
                    severity="high",
                    title="t",
                    description="d",
                    recommendation="r",
                    file="x.py",
                    line=5,
                )
            ],
        )
        mock_create_agent.return_value = _agent_returning([], structured)

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        issue = result["issues"][0]
        assert issue["category"] == "security"
        assert issue["source"] == "investigator:security"
        assert issue["severity"] == "high"

    @patch("src.agents.investigator.create_agent")
    def test_invalid_severity_normalized_to_medium(self, mock_create_agent):
        structured = InvestigationOutput(
            summary="s",
            score=50.0,
            issues=[
                IssueOutput(severity="URGENT!!", title="t", description="d", recommendation="r")
            ],
        )
        mock_create_agent.return_value = _agent_returning([], structured)

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert result["issues"][0]["severity"] == "medium"

    @patch("src.agents.investigator.create_agent")
    def test_score_clamped_to_0_100(self, mock_create_agent):
        structured = InvestigationOutput(summary="s", score=150.0, issues=[])
        mock_create_agent.return_value = _agent_returning([], structured)

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert result["score"] == 100.0

    @patch("src.agents.investigator.create_agent")
    def test_recursion_limit_hit_falls_back_gracefully(self, mock_create_agent):
        mock_agent = Mock()
        mock_agent.invoke = Mock(side_effect=GraphRecursionError("limit reached"))
        mock_create_agent.return_value = mock_agent

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=3,
        )

        assert result["investigation_depth"] == "deep"
        assert result["issues"] == []
        assert "budget" in result["summary"]

    @patch("src.agents.investigator.create_agent")
    def test_generic_failure_falls_back_gracefully(self, mock_create_agent):
        mock_agent = Mock()
        mock_agent.invoke = Mock(side_effect=RuntimeError("connection reset"))
        mock_create_agent.return_value = mock_agent

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
        )

        assert result["issues"] == []
        assert "failed" in result["summary"]

    @patch("src.agents.investigator.create_agent")
    def test_timeout_falls_back_gracefully_without_waiting_for_the_stuck_call(
        self, mock_create_agent
    ):
        """`investigator_timeout_seconds` used to be dead config -- nothing
        actually bounded a stuck `agent.invoke()` call. This confirms the
        wrapper returns a fallback promptly instead of blocking forever."""
        import time

        def slow_invoke(*args, **kwargs):
            time.sleep(2)
            return {
                "messages": [],
                "structured_response": InvestigationOutput(summary="s", score=100.0, issues=[]),
            }

        mock_agent = Mock()
        mock_agent.invoke = Mock(side_effect=slow_invoke)
        mock_create_agent.return_value = mock_agent

        start = time.monotonic()
        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=3,
            timeout_seconds=0.2,
        )
        elapsed = time.monotonic() - start

        assert elapsed < 1.5
        assert result["issues"] == []
        assert "time budget" in result["summary"]

    @patch("src.agents.investigator.create_agent")
    def test_recursion_limit_config_scales_with_max_tool_calls(self, mock_create_agent):
        mock_agent = _agent_returning([], InvestigationOutput(summary="s", score=100.0, issues=[]))
        mock_create_agent.return_value = mock_agent

        investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=5,
        )

        _, kwargs = mock_agent.invoke.call_args
        assert kwargs["config"]["recursion_limit"] == 5 * 2 + 4

    @patch("src.agents.investigator.create_agent")
    def test_open_circuit_breaker_falls_back_without_calling_agent(self, mock_create_agent):
        mock_agent = _agent_returning([], InvestigationOutput(summary="s", score=100.0, issues=[]))
        mock_create_agent.return_value = mock_agent
        breaker = CircuitBreaker(failure_threshold=1, timeout=300, name="test")
        breaker._on_failure()  # simulate an earlier failure elsewhere in this run

        result = investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
            llm_breaker=breaker,
        )

        assert result["investigation_depth"] == "deep"
        assert "circuit breaker" in result["summary"].lower()
        mock_agent.invoke.assert_not_called()

    @patch("src.agents.investigator.create_agent")
    def test_records_budget_usage_from_real_message_metadata(self, mock_create_agent):
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "a.py"}, "id": "c1"}],
                usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            ),
            ToolMessage(content="file contents", tool_call_id="c1"),
        ]
        structured = InvestigationOutput(summary="s", score=100.0, issues=[])
        mock_create_agent.return_value = _agent_returning(messages, structured)
        budget = LLMBudgetTracker(max_tokens=100_000)

        investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={},
            max_tool_calls=8,
            llm_budget=budget,
        )

        # At least the real 120 tokens from the AIMessage, plus estimates for
        # the prompt and the tool message -- so strictly more than 120.
        assert budget.usage()["used_tokens"] > 120

    @patch("src.agents.investigator.create_agent")
    def test_records_estimated_budget_usage_without_real_metadata(self, mock_create_agent):
        mock_agent = _agent_returning([], InvestigationOutput(summary="s", score=100.0, issues=[]))
        mock_create_agent.return_value = mock_agent
        budget = LLMBudgetTracker(max_tokens=100_000)

        investigate(
            category=Category.SECURITY,
            system_prompt="p",
            tools=[],
            llm_client=Mock(),
            recon_data={"github_metadata": {"readme_content": "x"}},
            max_tool_calls=8,
            llm_budget=budget,
        )

        assert budget.usage()["used_tokens"] > 0


class TestSummarizeReconData:
    def test_truncates_long_text_field(self):
        long_readme = "a" * 5000
        result = summarize_recon_data({"github_metadata": {"readme_content": long_readme}})

        truncated = result["github_metadata"]["readme_content"]
        assert len(truncated) < 5000
        assert "truncated" in truncated

    def test_leaves_short_text_untouched(self):
        result = summarize_recon_data({"github_metadata": {"readme_content": "short"}})
        assert result["github_metadata"]["readme_content"] == "short"

    def test_truncates_long_lists_and_notes_how_many_were_dropped(self):
        findings = [{"rule": f"R{i}"} for i in range(50)]
        result = summarize_recon_data({"static_analysis": {"findings": findings}})

        summarized = result["static_analysis"]["findings"]
        assert len(summarized) == 16  # 15 kept + one "... and N more" marker
        assert "35 more" in summarized[-1]

    def test_leaves_short_lists_untouched(self):
        findings = [{"rule": "R1"}, {"rule": "R2"}]
        result = summarize_recon_data({"static_analysis": {"findings": findings}})
        assert result["static_analysis"]["findings"] == findings

    def test_recurses_into_nested_dicts(self):
        data = {
            "github_metadata": {
                "readme_content": "a" * 5000,
                "file_structure": {"has_tests": True},
            }
        }
        result = summarize_recon_data(data)

        assert len(result["github_metadata"]["readme_content"]) < 5000
        assert result["github_metadata"]["file_structure"] == {"has_tests": True}

    def test_does_not_mutate_the_original_recon_data(self):
        original_findings = [{"rule": f"R{i}"} for i in range(50)]
        data = {"static_analysis": {"findings": original_findings}}

        summarize_recon_data(data)

        assert len(original_findings) == 50
