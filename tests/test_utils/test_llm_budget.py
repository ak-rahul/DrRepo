"""Tests for the LLM token budget tracker."""

from unittest.mock import Mock

from src.utils.llm_budget import LLMBudgetTracker, estimate_tokens, extract_actual_tokens


class TestEstimateTokens:
    def test_estimates_roughly_four_chars_per_token(self):
        assert estimate_tokens("a" * 400) == 100

    def test_never_returns_zero_for_nonempty_text(self):
        assert estimate_tokens("hi") >= 1


class TestExtractActualTokens:
    def test_reads_usage_metadata_when_present(self):
        response = Mock(usage_metadata={"total_tokens": 123}, response_metadata={})
        assert extract_actual_tokens(response) == 123

    def test_falls_back_to_response_metadata_token_usage(self):
        response = Mock(
            spec=["response_metadata"], response_metadata={"token_usage": {"total_tokens": 456}}
        )
        assert extract_actual_tokens(response) == 456

    def test_returns_none_when_neither_present(self):
        response = Mock(spec=["content"], content="just text")
        assert extract_actual_tokens(response) is None

    def test_returns_none_when_usage_metadata_present_but_empty(self):
        response = Mock(usage_metadata={}, response_metadata={})
        assert extract_actual_tokens(response) is None


class TestLLMBudgetTracker:
    def test_starts_with_full_budget_remaining(self):
        tracker = LLMBudgetTracker(max_tokens=1000)
        assert tracker.remaining() == 1000

    def test_record_reduces_remaining(self):
        tracker = LLMBudgetTracker(max_tokens=1000)
        tracker.record(300)
        assert tracker.remaining() == 700

    def test_remaining_never_goes_negative(self):
        tracker = LLMBudgetTracker(max_tokens=100)
        tracker.record(500)
        assert tracker.remaining() == 0

    def test_has_budget_for_reflects_remaining(self):
        tracker = LLMBudgetTracker(max_tokens=1000)
        tracker.record(900)
        assert tracker.has_budget_for(100) is True
        assert tracker.has_budget_for(101) is False

    def test_non_positive_record_is_ignored(self):
        tracker = LLMBudgetTracker(max_tokens=1000)
        tracker.record(0)
        tracker.record(-50)
        assert tracker.remaining() == 1000

    def test_usage_reports_all_fields(self):
        tracker = LLMBudgetTracker(max_tokens=1000)
        tracker.record(250)
        assert tracker.usage() == {
            "used_tokens": 250,
            "max_tokens": 1000,
            "remaining_tokens": 750,
        }

    def test_concurrent_record_calls_are_thread_safe(self):
        import threading

        tracker = LLMBudgetTracker(max_tokens=100_000)

        def record_many():
            for _ in range(1000):
                tracker.record(1)

        threads = [threading.Thread(target=record_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.usage()["used_tokens"] == 10_000
