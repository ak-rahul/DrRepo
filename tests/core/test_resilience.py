"""Budget tracker, lookup cache, retry decorator, logging, errors."""

import logging
import threading
from unittest.mock import Mock

import pytest

from drrepo.core.budget import LLMBudgetTracker, estimate_tokens, extract_actual_tokens
from drrepo.core.cache import DependencyLookupCache
from drrepo.core.log import configure_logging, logger
from drrepo.core.retry import is_retryable_llm_error, retry_with_backoff


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
        budget = LLMBudgetTracker(1000)
        budget.record(300)
        budget.record(-5)
        assert budget.remaining() == 700
        assert budget.affordable_count(300) == 2
        assert budget.affordable_count(0) == 0
        assert budget.has_budget_for(700) and not budget.has_budget_for(701)

    def test_reset(self):
        budget = LLMBudgetTracker(100)
        budget.record(100)
        budget.reset()
        assert budget.usage() == {"used_tokens": 0, "max_tokens": 100, "remaining_tokens": 100}

    def test_thread_safe_record(self):
        budget = LLMBudgetTracker(10**9)
        threads = [
            threading.Thread(target=lambda: [budget.record(1) for _ in range(1000)])
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert budget.usage()["used_tokens"] == 8000


class TestCache:
    def test_osv_roundtrip_and_copy_semantics(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "requests", "2.0.0")
        assert cache.get_osv(key) is None
        cache.set_osv(key, ["GHSA-1"])
        got = cache.get_osv(key)
        assert got == ["GHSA-1"]
        got.append("mutated")
        assert cache.get_osv(key) == ["GHSA-1"]

    def test_license_distinguishes_none_from_miss(self):
        cache = DependencyLookupCache()
        key = ("npm", "left-pad", "1.0.0")
        assert cache.get_license(key) == (False, None)
        cache.set_license(key, None)
        assert cache.get_license(key) == (True, None)

    def test_stats(self):
        cache = DependencyLookupCache()
        cache.set_vuln("GHSA-1", {"id": "GHSA-1"})
        assert cache.stats() == {"osv_entries": 0, "vuln_entries": 1, "license_entries": 0}


class TestRetry:
    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("drrepo.core.retry.time.sleep", lambda _s: None)
        calls = []

        @retry_with_backoff(max_retries=2)
        def flaky() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError
            return "ok"

        assert flaky() == "ok"
        assert len(calls) == 3

    def test_gives_up_after_max_retries(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("drrepo.core.retry.time.sleep", sleeps.append)

        @retry_with_backoff(max_retries=3, initial_delay=1, backoff_factor=2, max_delay=3)
        def always() -> None:
            raise TimeoutError

        with pytest.raises(TimeoutError):
            always()
        assert sleeps == [1, 2, 3]  # capped by max_delay

    def test_should_retry_false_raises_immediately(self, monkeypatch):
        monkeypatch.setattr(
            "drrepo.core.retry.time.sleep", lambda _s: pytest.fail("should not sleep")
        )

        @retry_with_backoff(max_retries=5, should_retry=lambda e: False)
        def bad() -> None:
            raise PermissionError

        with pytest.raises(PermissionError):
            bad()

    def test_unlisted_exception_not_retried(self):
        calls = []

        @retry_with_backoff(max_retries=3, exceptions=(ConnectionError,))
        def wrong_type() -> None:
            calls.append(1)
            raise KeyError

        with pytest.raises(KeyError):
            wrong_type()
        assert calls == [1]

    @pytest.mark.parametrize(
        ("status", "retryable"),
        [(401, False), (403, False), (413, False), (429, True), (500, True), (None, True)],
    )
    def test_is_retryable_llm_error(self, status, retryable):
        error = Exception("x")
        error.status_code = status  # type: ignore[attr-defined]
        assert is_retryable_llm_error(error) is retryable

    def test_is_retryable_reads_response_status(self):
        error = Exception("x")
        error.response = Mock(status_code=401)  # type: ignore[attr-defined]
        assert is_retryable_llm_error(error) is False


class TestLogging:
    def test_configure_is_idempotent_and_honors_levels(self, tmp_path):
        log_file = tmp_path / "logs" / "app.log"
        configure_logging("DEBUG", log_file=log_file, console_level="WARNING")
        configure_logging("DEBUG", log_file=log_file, console_level="WARNING")
        try:
            assert len(logger.handlers) == 2
            console, file_handler = logger.handlers
            assert console.level == logging.WARNING
            assert file_handler.level == logging.DEBUG
            logger.debug("hello file")
            file_handler.flush()
            assert "hello file" in log_file.read_text(encoding="utf-8")
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_unknown_level_defaults_to_info(self):
        configure_logging("NOPE", log_file=None)
        try:
            assert logger.level == logging.INFO
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
