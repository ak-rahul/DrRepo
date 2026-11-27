import contextlib
import threading
import time
from unittest.mock import Mock

import pytest

from drrepo.errors import CircuitOpenError
from drrepo.resilience import (
    CircuitBreaker,
    CircuitState,
    is_retryable_llm_error,
    retry_with_backoff,
)


def _fail() -> None:
    raise ValueError("boom")


def test_success_passes_through_and_resets_count():
    breaker = CircuitBreaker(failure_threshold=2, timeout=60)
    with pytest.raises(ValueError):
        breaker.call(_fail)
    assert breaker.call(lambda: 7) == 7
    assert breaker.failure_count == 0
    assert breaker.state == CircuitState.CLOSED


def test_opens_after_threshold_and_rejects_without_calling():
    breaker = CircuitBreaker(failure_threshold=2, timeout=60)
    for _ in range(2):
        with pytest.raises(ValueError):
            breaker.call(_fail)
    assert breaker.state == CircuitState.OPEN

    called = []
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: called.append(1))
    assert called == []


def test_half_open_probe_success_closes(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, timeout=10)
    with pytest.raises(ValueError):
        breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.resilience.time.monotonic", lambda: start + 11)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitState.CLOSED


def test_half_open_probe_failure_reopens(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=3, timeout=10)
    for _ in range(3):
        with pytest.raises(ValueError):
            breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.resilience.time.monotonic", lambda: start + 11)
    with pytest.raises(ValueError):
        breaker.call(_fail)  # the single probe fails -> straight back to OPEN
    assert breaker.state == CircuitState.OPEN


def test_only_one_probe_in_flight(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, timeout=10)
    with pytest.raises(ValueError):
        breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.resilience.time.monotonic", lambda: start + 11)

    release = threading.Event()
    entered = threading.Event()

    def slow_probe() -> str:
        entered.set()
        release.wait(5)
        return "done"

    results: list[str] = []
    thread = threading.Thread(target=lambda: results.append(breaker.call(slow_probe)))
    thread.start()
    entered.wait(5)
    with pytest.raises(CircuitOpenError, match="probe in flight"):
        breaker.call(lambda: "second")
    release.set()
    thread.join(5)
    assert results == ["done"]
    assert breaker.state == CircuitState.CLOSED


def test_non_counted_exception_releases_probe_slot(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, timeout=10, expected_exception=ValueError)
    with pytest.raises(ValueError):
        breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.resilience.time.monotonic", lambda: start + 11)

    def interrupt() -> None:
        raise KeyError("not a counted failure")

    with pytest.raises(KeyError):
        breaker.call(interrupt)
    assert breaker.call(lambda: 1) == 1  # slot was released, probe succeeds


def test_concurrent_failures_are_all_counted():
    breaker = CircuitBreaker(failure_threshold=1000, timeout=60)

    def worker() -> None:
        for _ in range(50):
            with contextlib.suppress(ValueError):
                breaker.call(_fail)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert breaker.failure_count == 400


def test_reset_and_state_snapshot():
    breaker = CircuitBreaker(failure_threshold=1, timeout=60, name="llm")
    with pytest.raises(ValueError):
        breaker.call(_fail)
    breaker.reset()
    assert breaker.get_state() == {
        "name": "llm",
        "state": "closed",
        "failure_count": 0,
        "failure_threshold": 1,
        "timeout": 60,
    }


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0)


class TestRetry:
    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("drrepo.resilience.time.sleep", lambda _s: None)
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
        monkeypatch.setattr("drrepo.resilience.time.sleep", sleeps.append)

        @retry_with_backoff(max_retries=3, initial_delay=1, backoff_factor=2, max_delay=3)
        def always() -> None:
            raise TimeoutError

        with pytest.raises(TimeoutError):
            always()
        assert sleeps == [1, 2, 3]  # capped by max_delay

    def test_should_retry_false_raises_immediately(self, monkeypatch):
        monkeypatch.setattr(
            "drrepo.resilience.time.sleep", lambda _s: pytest.fail("should not sleep")
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
