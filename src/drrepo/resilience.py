"""Failure handling for calls to flaky external services: a circuit breaker and a
retry decorator.

Composition used for every LLM call (see `agents/llm.py`):

    breaker.call( retry_with_backoff(client.invoke) )

The breaker wraps the retry loop, never the reverse: retries absorb one
transient blip inside a logical call, the breaker stops *new* logical calls
once failures are sustained. With retry outside, every attempt would pay full
backoff against an already-open circuit.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

from drrepo.errors import CircuitOpenError
from drrepo.log import logger

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

# ------------------------------------------------------------- breaker ---


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker shared by every LLM call site in a process.

    CLOSED     calls pass through; consecutive failures are counted.
    OPEN       `failure_threshold` consecutive failures were seen; calls are
               rejected instantly with `CircuitOpenError` for `timeout` seconds.
    HALF_OPEN  the timeout elapsed; exactly one probe call is let through.
               Success closes the circuit, failure re-opens it, and callers that
               arrive while the probe is in flight are rejected -- so a dead
               provider is never hit by a burst of parallel probes.
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
        self._lock = threading.Lock()

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run `func(*args, **kwargs)` under breaker protection.

        Raises:
            CircuitOpenError: the circuit is open (or a probe is running); `func` was not called.
            Exception: whatever `func` raised, after recording the failure.
        """
        is_probe = self._admit()
        try:
            result = func(*args, **kwargs)
        except self.expected_exception:
            self._on_failure(is_probe)
            raise
        except BaseException:
            # Not a counted failure (e.g. KeyboardInterrupt), but a probe slot
            # must never leak or the breaker would reject forever.
            if is_probe:
                with self._lock:
                    self._probe_in_flight = False
            raise
        self._on_success()
        return result

    def _admit(self) -> bool:
        """Admit or reject a call. Returns True if this call is the half-open probe."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return False
            if self.state == CircuitState.OPEN:
                elapsed = time.monotonic() - (self.last_failure_time or 0.0)
                if elapsed < self.timeout:
                    raise CircuitOpenError(
                        f"Circuit breaker '{self.name}' is OPEN; retry after {self.timeout - elapsed:.0f}s"
                    )
                logger.info(f"CircuitBreaker '{self.name}': attempting recovery (HALF_OPEN)")
                self.state = CircuitState.HALF_OPEN
            if self._probe_in_flight:
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is HALF_OPEN with a probe in flight"
                )
            self._probe_in_flight = True
            return True

    def _on_success(self) -> None:
        with self._lock:
            if self.state != CircuitState.CLOSED:
                logger.info(f"CircuitBreaker '{self.name}': recovered, closing circuit")
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
                f"CircuitBreaker '{self.name}': failure {self.failure_count}/{self.failure_threshold}"
            )
            if is_probe or self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.error(f"CircuitBreaker '{self.name}': opening circuit")
                self.state = CircuitState.OPEN

    def reset(self) -> None:
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


# --------------------------------------------------------------- retry ---


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[BaseException], bool] | None = None,
) -> Callable[[F], F]:
    """Retry the decorated function with exponential backoff.

    Up to `max_retries + 1` calls; delays are `initial_delay * backoff_factor**n`
    capped at `max_delay`. `should_retry(e) -> False` re-raises immediately, for
    errors that can't succeed on a second try (bad credentials, 404s).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                except exceptions as e:
                    retryable = should_retry(e) if should_retry else True
                    if not retryable or attempt >= max_retries:
                        if retryable:
                            logger.error(
                                f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                            )
                        raise
                    wait = min(initial_delay * (backoff_factor**attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                else:
                    if attempt > 0:
                        logger.info(f"{func.__name__} succeeded on attempt {attempt + 1}")
                    return result
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper  # type: ignore[return-value]

    return decorator


_PERMANENT_HTTP_STATUSES = frozenset({400, 401, 403, 404, 413, 422})


def is_retryable_llm_error(error: BaseException) -> bool:
    """False for LLM errors that fail identically on every retry.

    An open circuit and HTTP 400/401/403/404/413/422 (bad request, auth, too
    large) are permanent for the run; retrying only burns backoff. Rate limits
    (429) and 5xx are retried. Duck-typed on `status_code` so it works for the
    Groq and OpenAI SDKs without importing either.
    """
    if isinstance(error, CircuitOpenError):
        return False
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return not (isinstance(status, int) and status in _PERMANENT_HTTP_STATUSES)
