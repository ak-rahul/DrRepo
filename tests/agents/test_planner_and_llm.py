from unittest.mock import MagicMock

import pytest

from drrepo.agents.llm import LLMRuntime, build_chat_model
from drrepo.agents.planner import (
    CategoryPlanOutput,
    InvestigationPlanOutput,
    LeadInvestigator,
    enforce_deep_cap,
    plan_from_output,
)
from drrepo.config import Config
from drrepo.core.budget import LLMBudgetTracker
from drrepo.core.circuit_breaker import CircuitBreaker
from drrepo.core.errors import CircuitOpenError
from drrepo.models import Category, InvestigationDepth


def _output(**depths: str) -> InvestigationPlanOutput:
    return InvestigationPlanOutput(
        plans=[
            CategoryPlanOutput(category=c, depth=d, rationale=f"{c} because")
            for c, d in depths.items()
        ]  # type: ignore[arg-type]
    )


def _llm_returning(result) -> LLMRuntime:
    client = MagicMock()
    client.with_structured_output.return_value.invoke.return_value = result
    return LLMRuntime(client=client, budget=LLMBudgetTracker(10_000))


class TestPlanner:
    def test_plan_from_output_fills_missing_categories(self):
        plan = plan_from_output(_output(security="deep"))
        assert plan.depth_for(Category.SECURITY) == InvestigationDepth.DEEP
        assert plan.depth_for(Category.DOCUMENTATION) == InvestigationDepth.SHALLOW
        assert "defaulted" in plan.plans["documentation"].rationale

    def test_deep_cap_keeps_highest_priority(self):
        plan = plan_from_output(_output(documentation="deep", security="deep", dependencies="deep"))
        capped = enforce_deep_cap(plan, 2)
        assert set(capped.deep_categories()) == {Category.SECURITY, Category.DEPENDENCIES}
        assert "downgraded" in capped.plans["documentation"].rationale

    def test_plan_calls_structured_output_and_records_budget(self):
        llm = _llm_returning(_output(security="deep", code_quality="deep"))
        plan = LeadInvestigator(llm).plan({"stars": 1}, max_deep=1, user_context="focus on auth")
        assert plan.deep_categories() == [Category.SECURITY]
        messages = llm.client.with_structured_output.return_value.invoke.call_args.args[0]
        assert "focus on auth" in messages[1].content and "at most 1" in messages[1].content
        assert llm.budget.usage()["used_tokens"] > 0

    def test_zero_budget_skips_llm(self):
        llm = _llm_returning(_output(security="deep"))
        plan = LeadInvestigator(llm).plan({}, max_deep=0)
        assert plan.deep_categories() == []
        llm.client.with_structured_output.assert_not_called()

    def test_failure_defaults_to_all_shallow(self):
        client = MagicMock()
        client.with_structured_output.return_value.invoke.side_effect = CircuitOpenError("open")
        plan = LeadInvestigator(LLMRuntime(client=client)).plan({}, max_deep=5)
        assert plan.deep_categories() == []
        assert "CircuitOpenError" in plan.plans["security"].rationale

    def test_output_schema_rejects_bad_values(self):
        with pytest.raises(ValueError):
            CategoryPlanOutput(category="security", depth="medium", rationale="x")  # type: ignore[arg-type]


class TestLLMRuntime:
    def test_complete_records_actual_tokens(self, fake_chat_model):
        llm = LLMRuntime(client=fake_chat_model, budget=LLMBudgetTracker(1000))
        assert llm.complete("sys", "user") == "A concise LLM narrative."
        assert llm.budget.usage()["used_tokens"] == 42

    def test_breaker_wraps_retry(self, monkeypatch):
        """Retries happen inside one breaker call: 1 logical failure, not 3."""
        monkeypatch.setattr("drrepo.core.retry.time.sleep", lambda _s: None)
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

    def test_unknown_provider(self):
        with pytest.raises(ValueError):
            build_chat_model(Config(model_provider="nope"))
