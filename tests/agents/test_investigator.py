"""Investigator wrapper logic. `create_agent` is mocked: GenericFakeChatModel has no
`bind_tools`, so it can't drive a real agent graph; the live check is in
tests/integration."""

import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from drrepo.agents.investigator import (
    InvestigationError,
    InvestigationOutput,
    IssueOutput,
    build_prompt,
    extract_trace,
    investigate,
    summarize_recon_data,
)
from drrepo.agents.llm import LLMRuntime, TokenBudget
from drrepo.errors import CircuitOpenError
from drrepo.models import Category, Issue, Severity


def _messages():
    return [
        AIMessage(
            content="", tool_calls=[{"name": "read_file", "args": {"path": "a.py"}, "id": "c1"}]
        ),
        ToolMessage(content="1| import os", tool_call_id="c1"),
        AIMessage(content="", tool_calls=[{"name": "InvestigationOutput", "args": {}, "id": "c2"}]),
        ToolMessage(content="submitted", tool_call_id="c2"),
    ]


def _run(agent_result=None, side_effect=None, **kwargs):
    agent = MagicMock()
    if side_effect is not None:
        agent.invoke.side_effect = side_effect
    else:
        agent.invoke.return_value = agent_result
    llm = kwargs.pop("llm", LLMRuntime(client=MagicMock(), budget=TokenBudget(100_000)))
    with patch("langchain.agents.create_agent", return_value=agent) as create:
        result = investigate(
            category=Category.SECURITY,
            system_prompt="investigate",
            tools=[],
            llm=llm,
            recon_data={"security": {"findings": []}},
            known_issues=[],
            max_tool_calls=3,
            **kwargs,
        )
    return result, agent, create, llm


def test_success_normalizes_issues_and_extracts_trace():
    structured = InvestigationOutput(
        summary=" Found one. ",
        issues=[
            IssueOutput(
                severity="URGENT",
                title="SQL injection",
                description="d",
                recommendation="r",
                file="./app/db.py",
                line=4,
            ),
            IssueOutput(
                severity="low", title="  ", description="", recommendation=""
            ),  # blank title dropped
        ],
    )
    result, agent, create, llm = _run({"messages": _messages(), "structured_response": structured})
    assert result.summary == "Found one."
    [issue] = result.issues
    assert issue.severity == Severity.MEDIUM  # unknown severity -> medium
    assert issue.file == "app/db.py" and issue.source == "investigator:security"
    assert [t.tool for t in result.trace] == ["read_file"]  # synthetic submit call excluded
    assert agent.invoke.call_args.kwargs["config"] == {"recursion_limit": 10}
    assert create.call_args.kwargs["response_format"] is InvestigationOutput
    assert llm.budget.usage()["used_tokens"] > 0


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (GraphRecursionError("x"), "tool-call budget"),
        (CircuitOpenError("x"), "circuit breaker"),
        (RuntimeError("provider exploded"), "RuntimeError"),
    ],
)
def test_failures_raise_investigation_error(error, fragment):
    with pytest.raises(InvestigationError, match=fragment):
        _run(side_effect=error)


def test_missing_structured_response():
    with pytest.raises(InvestigationError, match="structured"):
        _run({"messages": []})


def test_timeout():
    def slow(*_a, **_k):
        time.sleep(2)

    start = time.monotonic()
    with pytest.raises(InvestigationError, match="time budget"):
        _run(side_effect=slow, timeout_seconds=0.2)
    assert time.monotonic() - start < 1.5


def test_runs_under_breaker():
    breaker = MagicMock()
    breaker.call.side_effect = CircuitOpenError("open")
    with pytest.raises(InvestigationError, match="circuit"):
        _run({"messages": []}, llm=LLMRuntime(client=MagicMock(), breaker=breaker))


def test_summarize_bounds_text_and_lists():
    data = summarize_recon_data({"readme": {"text": "x" * 5000, "items": list(range(40))}})
    assert len(data["readme"]["text"]) < 1600
    assert data["readme"]["items"][-1] == "... and 25 more"


def test_prompt_lists_known_issues_and_context():
    known = [Issue(Severity.HIGH, Category.SECURITY, "Known thing", "", "", "bandit")]
    prompt = build_prompt({"a": {}}, known, user_context="payments code")
    assert "Known thing" in prompt and "payments code" in prompt


def test_extract_trace_ignores_unmatched_messages():
    assert extract_trace([ToolMessage(content="orphan", tool_call_id="zzz")]) == []
