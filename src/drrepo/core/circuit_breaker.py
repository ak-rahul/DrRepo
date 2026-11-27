"""Thread-safe circuit breaker shared by every LLM call site in a run.

States:
    CLOSED     normal operation; calls pass through and failures are counted.
    OPEN       `failure_threshold` consecutive failures were seen; calls are
               rejected instantly with `CircuitOpenError` until `timeout`
               seconds have passed since the last failure.
    HALF_OPEN  the timeout elapsed; exactly one probe call is let through.
               Success closes the circuit, failure re-opens it. Other callers
               arriving while the probe is in flight are rejected, so a dead
               provider is never hit by a burst of parallel probes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

from drrepo.core.errors import CircuitOpenError
from drrepo.core.log import logger

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Fail fast once a dependency is known to be down.

    Example:
        breaker = CircuitBreaker(failure_threshold=3, timeout=300, name="llm")
        result = breaker.call(client.invoke, messages)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60,
        expected_exception: type[BaseException] = Exception,
        name: str = "circuit",
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.name = name

        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = CircuitState.CLOSED
        self._probe_in_flight = False
        # One breaker instance is shared across category nodes that LangGraph
        # runs concurrently, so every state transition happens under this lock.
        self._lock = threading.Lock()

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run `func(*args, **kwargs)` under breaker protection.

        Raises:
            CircuitOpenError: the circuit is open (or a half-open probe is
                already running), so `func` was not called at all.
            Exception: whatever `func` raised, after recording the failure.
        """
        is_probe = self._before_call()
        try:
            result = func(*args, **kwargs)
        except self.expected_exception:
            self._on_failure(is_probe)
            raise
        except BaseException:
            # Not a failure we count (e.g. KeyboardInterrupt) -- but a probe
            # slot must never leak, or the breaker would stay stuck rejecting.
            if is_probe:
                with self._lock:
                    self._probe_in_flight = False
            raise
        self._on_success()
        return result

    def _before_call(self) -> bool:
        """Admit or reject a call. Returns True if this call is the half-open probe."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return False

            if self.state == CircuitState.OPEN:
                elapsed = time.monotonic() - (self.last_failure_time or 0.0)
                if elapsed < self.timeout:
                    raise CircuitOpenError(
                        f"Circuit breaker '{self.name}' is OPEN; "
                        f"retry after {self.timeout - elapsed:.0f}s"
                    )
                logger.info(f"CircuitBreaker '{self.name}': attempting recovery (HALF_OPEN)")
                self.state = CircuitState.HALF_OPEN

            # HALF_OPEN: let exactly one probe through.
            if self._probe_in_flight:
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is HALF_OPEN with a probe in flight"
                )
            self._probe_in_flight = True
            return True

    def _on_success(self) -> None:
        with self._lock:
            if self.state != CircuitState.CLOSED:
                logger.info(f"CircuitBreaker '{self.name}': recovery successful, closing circuit")
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            self._probe_in_flight = False

    def _on_failure(self, is_probe: bool) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if is_probe:
                self._probe_in_flight = False
            logger.warning(
                f"CircuitBreaker '{self.name}': failure "
                f"{self.failure_count}/{self.failure_threshold}"
            )
            if is_probe or self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.error(f"CircuitBreaker '{self.name}': opening circuit")
                self.state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually force the breaker back to CLOSED."""
        with self._lock:
            self.failure_count = 0
            self.last_failure_time = None
            self.state = CircuitState.CLOSED
            self._probe_in_flight = False

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "timeout": self.timeout,
            }
