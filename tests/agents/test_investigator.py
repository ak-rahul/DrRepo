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
    _model_retry_middleware,
    build_prompt,
    extract_trace,
    investigate,
    retry_after_seconds,
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
    assert agent.invoke.call_args.kwargs["config"] == {"recursion_limit": 14}  # 3 calls + wrap-up
    strategy = create.call_args.kwargs["response_format"]
    assert strategy.schema is InvestigationOutput  # a ToolStrategy: never json mode with tools
    names = [type(m).__name__ for m in create.call_args.kwargs["middleware"]]
    assert names[:2] == ["ProviderRetry", "ToolBudget"]
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


class _RateLimited(Exception):
    status_code = 429

    def __init__(self, retry_after=None):
        super().__init__("rate limited")
        self.response = MagicMock(headers={"retry-after": retry_after} if retry_after else {})


class TestProviderRetry:
    def test_honors_retry_after_then_succeeds(self):
        middleware = _model_retry_middleware(deadline=None)
        handler = MagicMock(side_effect=[_RateLimited("7"), "ok"])
        with patch("drrepo.agents.investigator.time.sleep") as sleep:
            assert middleware.wrap_model_call("request", handler) == "ok"
        sleep.assert_called_once_with(7.0)
        assert retry_after_seconds(_RateLimited("x")) is None

    def test_permanent_errors_and_exhausted_retries_raise(self):
        class Unauthorized(Exception):
            status_code = 401

        middleware = _model_retry_middleware(deadline=None)
        with pytest.raises(Unauthorized):
            middleware.wrap_model_call("r", MagicMock(side_effect=Unauthorized()))
        with patch("drrepo.agents.investigator.time.sleep"), pytest.raises(_RateLimited):
            middleware.wrap_model_call("r", MagicMock(side_effect=_RateLimited()))

    def test_a_long_retry_after_fails_at_once(self):
        middleware = _model_retry_middleware(deadline=None)
        with patch("drrepo.agents.investigator.time.sleep") as sleep, pytest.raises(_RateLimited):
            middleware.wrap_model_call("r", MagicMock(side_effect=_RateLimited("3600")))
        sleep.assert_not_called()

    def test_never_waits_past_the_time_budget(self):
        middleware = _model_retry_middleware(deadline=time.monotonic() + 1)
        with patch("drrepo.agents.investigator.time.sleep") as sleep, pytest.raises(_RateLimited):
            middleware.wrap_model_call("r", MagicMock(side_effect=_RateLimited("42")))
        sleep.assert_not_called()


def test_readme_content_stays_out_of_the_prompt():
    summary = summarize_recon_data({"repo_layout": {"readme_content": "# big", "has_ci": True}})
    assert summary == {"repo_layout": {"has_ci": True}}


def test_every_category_fits_a_small_request_budget(tmp_path):
    """Instructions plus tool schemas, sent on every model call, stay well under the
    7,000-token request cap that Groq's free tier needs (see INVESTIGATION_CONTEXT_TOKENS)."""
    from drrepo.agents.analysts import default_analysts
    from drrepo.agents.investigator import _fixed_tokens
    from drrepo.agents.tools import build_tools
    from drrepo.config import Config

    for analyst in default_analysts().values():
        tools = build_tools(analyst.tool_families, clone_root=str(tmp_path), config=Config())
        assert _fixed_tokens(analyst.investigation_prompt, tools) < 2500, analyst.category
        assert analyst.recon_inputs, analyst.category  # every built-in analyst scopes its recon


def test_tool_budget_answers_calls_over_the_limit_without_running_them():
    from langchain_core.messages import ToolMessage

    from drrepo.agents.investigator import BUDGET_SPENT, _tool_budget_middleware

    budget = _tool_budget_middleware(2)
    handler = MagicMock(return_value=ToolMessage(content="ran", tool_call_id="x"))
    requests = [MagicMock(tool_call={"id": f"c{i}", "name": "read_file"}) for i in range(3)]
    results = [budget.wrap_tool_call(r, handler) for r in requests]
    assert [r.content for r in results] == ["ran", "ran", BUDGET_SPENT]
    assert handler.call_count == 2 and results[2].tool_call_id == "c2"
    # A refused call is not an investigation step.
    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "c2"}]),
        results[2],
    ]
    assert extract_trace(messages) == []


def test_provider_errors_are_described_without_their_raw_message():
    from drrepo.agents.investigator import describe_llm_error

    class RateLimitError(Exception):
        status_code = 429

    secret = "Rate limit reached for model in organization `org_01abc` on tokens per day (TPD)"
    described = describe_llm_error(RateLimitError(secret))
    assert described == "RateLimitError (HTTP 429): the provider's daily quota is used up"
    assert "org_" not in describe_llm_error(RateLimitError("org_01abc tokens per minute"))
    assert describe_llm_error(ValueError("bad output")) == "ValueError: bad output"
