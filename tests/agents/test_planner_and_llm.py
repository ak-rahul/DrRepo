import threading
from unittest.mock import MagicMock, Mock

import pytest

from drrepo.agents.llm import (
    LLMRuntime,
    TokenBudget,
    build_chat_model,
    estimate_tokens,
    extract_actual_tokens,
)
from drrepo.agents.planner import (
    CategoryPlanOutput,
    InvestigationPlanOutput,
    LeadInvestigator,
    enforce_deep_cap,
    plan_from_output,
)
from drrepo.config import Config
from drrepo.errors import CircuitOpenError
from drrepo.models import Category, InvestigationDepth
from drrepo.resilience import CircuitBreaker


def _output(**depths: str) -> InvestigationPlanOutput:
    return InvestigationPlanOutput(
        plans=[
            CategoryPlanOutput(category=c, depth=d, rationale=f"{c} because")
            for c, d in depths.items()
        ]
    )


def _deep(plan) -> list[Category]:
    return [c for c in Category if plan.depth_for(c) == InvestigationDepth.DEEP]


def _llm_returning(result) -> LLMRuntime:
    client = MagicMock()
    client.with_structured_output.return_value.invoke.return_value = result
    return LLMRuntime(client=client, budget=TokenBudget(10_000))


class TestPlanner:
    def test_plan_from_output_fills_missing_categories(self):
        plan = plan_from_output(_output(security="deep"))
        assert plan.depth_for(Category.SECURITY) == InvestigationDepth.DEEP
        assert plan.depth_for(Category.DOCUMENTATION) == InvestigationDepth.SHALLOW
        assert "defaulted" in plan.plans["documentation"].rationale

    def test_deep_cap_keeps_highest_priority(self):
        plan = plan_from_output(_output(documentation="deep", security="deep", dependencies="deep"))
        capped = enforce_deep_cap(plan, 2)
        assert set(_deep(capped)) == {Category.SECURITY, Category.DEPENDENCIES}
        assert "downgraded" in capped.plans["documentation"].rationale

    def test_plan_calls_structured_output_and_records_budget(self):
        llm = _llm_returning(_output(security="deep", code_quality="deep"))
        plan = LeadInvestigator(llm).plan({"stars": 1}, max_deep=1, user_context="focus on auth")
        assert _deep(plan) == [Category.SECURITY]
        messages = llm.client.with_structured_output.return_value.invoke.call_args.args[0]
        assert "focus on auth" in messages[1].content and "at most 1" in messages[1].content
        assert llm.budget.usage()["used_tokens"] > 0

    def test_zero_budget_skips_llm(self):
        llm = _llm_returning(_output(security="deep"))
        plan = LeadInvestigator(llm).plan({}, max_deep=0)
        assert _deep(plan) == []
        llm.client.with_structured_output.assert_not_called()

    def test_failure_defaults_to_all_shallow(self):
        client = MagicMock()
        client.with_structured_output.return_value.invoke.side_effect = CircuitOpenError("open")
        plan = LeadInvestigator(LLMRuntime(client=client)).plan({}, max_deep=5)
        assert _deep(plan) == []
        assert "CircuitOpenError" in plan.plans["security"].rationale

    def test_output_schema_rejects_bad_values(self):
        with pytest.raises(ValueError):
            CategoryPlanOutput(category="security", depth="medium", rationale="x")


class TestLLMRuntime:
    def test_complete_records_actual_tokens(self, fake_chat_model):
        llm = LLMRuntime(client=fake_chat_model, budget=TokenBudget(1000))
        assert llm.complete("sys", "user") == "A concise LLM narrative."
        assert llm.budget.usage()["used_tokens"] == 42

    def test_breaker_wraps_retry(self, monkeypatch):
        """Retries happen inside one breaker call: 1 logical failure, not 3."""
        monkeypatch.setattr("drrepo.resilience.time.sleep", lambda _s: None)
        client = MagicMock()
        client.invoke.side_effect = ConnectionError("down")
        breaker = CircuitBreaker(failure_threshold=5)
        llm = LLMRuntime(client=client, breaker=breaker)
        with pytest.raises(ConnectionError):
            llm.complete("s", "u")
        assert client.invoke.call_count == 3  # 1 + 2 retries
        assert breaker.failure_count == 1

    def test_auth_errors_not_retried(self):
        error = Exception("unauthorized")
        error.status_code = 401  # type: ignore[attr-defined]
        client = MagicMock()
        client.invoke.side_effect = error
        with pytest.raises(Exception, match="unauthorized"):
            LLMRuntime(client=client).complete("s", "u")
        assert client.invoke.call_count == 1

    def test_available(self):
        assert LLMRuntime(client=None).available is False


class TestBuildChatModel:
    def test_groq(self):
        model = build_chat_model(
            Config(groq_api_key="k", max_tokens=123, llm_request_timeout_seconds=7)
        )
        assert type(model).__name__ == "ChatGroq"
        assert model.max_tokens == 123 and model.max_retries == 0

    def test_openai(self):
        model = build_chat_model(
            Config(model_provider="openai", openai_api_key="k", model_name="gpt-4o-mini")
        )
        assert type(model).__name__ == "ChatOpenAI" and model.max_retries == 0

    def test_unknown_provider_is_rejected_by_config(self):
        from drrepo.errors import ConfigurationError

        with pytest.raises(ConfigurationError, match="MODEL_PROVIDER"):
            Config(model_provider="nope")


class TestBudget:
    def test_estimate_is_at_least_one(self):
        assert estimate_tokens("") == 1
        assert estimate_tokens("x" * 400) == 100

    def test_extract_prefers_usage_metadata(self):
        assert extract_actual_tokens(Mock(usage_metadata={"total_tokens": 12})) == 12

    def test_extract_falls_back_to_response_metadata(self):
        response = Mock(usage_metadata=None, response_metadata={"token_usage": {"total_tokens": 9}})
        assert extract_actual_tokens(response) == 9

    def test_extract_returns_none_for_bare_mock(self):
        # A plain Mock auto-vivifies attributes; the isinstance guards must reject them.
        assert extract_actual_tokens(Mock()) is None

    def test_record_remaining_and_affordable(self):
        budget = TokenBudget(1000)
        budget.record(300)
        budget.record(-5)
        assert budget.remaining() == 700
        assert budget.affordable_count(300) == 2
        assert budget.affordable_count(0) == 0

    def test_reset(self):
        budget = TokenBudget(100)
        budget.record(100)
        budget.reset()
        assert budget.usage() == {"used_tokens": 0, "max_tokens": 100, "remaining_tokens": 100}

    def test_thread_safe_record(self):
        budget = TokenBudget(10**9)
        threads = [
            threading.Thread(target=lambda: [budget.record(1) for _ in range(1000)])
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert budget.usage()["used_tokens"] == 8000
