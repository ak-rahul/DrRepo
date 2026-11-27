import contextlib
import threading
import time

import pytest

from drrepo.core.circuit_breaker import CircuitBreaker, CircuitState
from drrepo.core.errors import CircuitOpenError


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
    monkeypatch.setattr("drrepo.core.circuit_breaker.time.monotonic", lambda: start + 11)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitState.CLOSED


def test_half_open_probe_failure_reopens(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=3, timeout=10)
    for _ in range(3):
        with pytest.raises(ValueError):
            breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.core.circuit_breaker.time.monotonic", lambda: start + 11)
    with pytest.raises(ValueError):
        breaker.call(_fail)  # the single probe fails -> straight back to OPEN
    assert breaker.state == CircuitState.OPEN


def test_only_one_probe_in_flight(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, timeout=10)
    with pytest.raises(ValueError):
        breaker.call(_fail)
    start = time.monotonic()
    monkeypatch.setattr("drrepo.core.circuit_breaker.time.monotonic", lambda: start + 11)

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
    monkeypatch.setattr("drrepo.core.circuit_breaker.time.monotonic", lambda: start + 11)

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
