"""Tests for BaseAnalystAgent's circuit-breaker and token-budget wiring.

Not tested elsewhere: every concrete analyst subclass shares this `_call_llm`
implementation, so these tests exercise it directly via a minimal concrete
subclass rather than duplicating the same checks per analyst.
"""

from unittest.mock import Mock

import pytest

from src.agents.base import BaseAnalystAgent
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.exceptions import APIConnectionError
from src.utils.llm_budget import LLMBudgetTracker


class _FakeAnalyst(BaseAnalystAgent):
    """Minimal concrete subclass -- `analyze()` isn't under test here."""

    def analyze(self, collector_results):
        raise NotImplementedError


class TestCallLlmWithoutBreakerOrBudget:
    def test_calls_through_directly_when_neither_configured(self, fake_llm_client):
        agent = _FakeAnalyst("Fake", "system prompt", fake_llm_client)

        result = agent._call_llm("hello")

        assert result == fake_llm_client.invoke.return_value.content
        fake_llm_client.invoke.assert_called_once()


class TestCallLlmWithCircuitBreaker:
    def test_successful_call_passes_through_breaker(self, fake_llm_client):
        breaker = CircuitBreaker(failure_threshold=3, timeout=60, name="test")
        agent = _FakeAnalyst("Fake", "system", fake_llm_client, llm_breaker=breaker)

        result = agent._call_llm("hello")

        assert result == fake_llm_client.invoke.return_value.content
        assert breaker.failure_count == 0

    def test_repeated_failures_open_the_breaker_and_short_circuit_further_calls(self, monkeypatch):
        # `_invoke_with_retry` retries transient failures with real backoff
        # sleeps -- mock those away so this test doesn't take ~14s per failing
        # logical call while still exercising the real retry-then-breaker path.
        monkeypatch.setattr("src.utils.retry.time.sleep", lambda *_: None)

        failing_client = Mock()
        failing_client.invoke = Mock(side_effect=RuntimeError("provider down"))
        breaker = CircuitBreaker(failure_threshold=2, timeout=300, name="test")
        agent = _FakeAnalyst("Fake", "system", failing_client, llm_breaker=breaker)

        # Each of these two outer calls exhausts its own internal retries
        # (4 real attempts each) but counts as exactly ONE breaker-tracked
        # failure -- the breaker guards against sustained failure across
        # logical calls, not against a single call's internal retry count.
        for _ in range(2):
            with pytest.raises(RuntimeError):
                agent._call_llm("hello")

        assert breaker.failure_count == 2

        # Third call: breaker is OPEN, so the client must not be invoked again.
        call_count_before = failing_client.invoke.call_count
        with pytest.raises(APIConnectionError):
            agent._call_llm("hello")
        assert failing_client.invoke.call_count == call_count_before


class TestCallLlmWithBudgetTracking:
    def test_records_actual_tokens_when_response_reports_usage(self, fake_llm_client):
        fake_llm_client.invoke.return_value = Mock(
            content="summary text", usage_metadata={"total_tokens": 250}
        )
        budget = LLMBudgetTracker(max_tokens=10_000)
        agent = _FakeAnalyst("Fake", "system", fake_llm_client, llm_budget=budget)

        agent._call_llm("hello")

        assert budget.usage()["used_tokens"] == 250

    def test_falls_back_to_estimate_when_response_has_no_usage_metadata(self, fake_llm_client):
        fake_llm_client.invoke.return_value = Mock(spec=["content"], content="x" * 400)
        budget = LLMBudgetTracker(max_tokens=10_000)
        agent = _FakeAnalyst("Fake", "system prompt", fake_llm_client, llm_budget=budget)

        agent._call_llm("user prompt")

        assert budget.usage()["used_tokens"] > 0

    def test_no_budget_tracker_means_no_tracking_attempted(self, fake_llm_client):
        agent = _FakeAnalyst("Fake", "system", fake_llm_client)
        # Must not raise even though llm_budget is None.
        agent._call_llm("hello")
