"""Circuit breaker pattern for external services."""

import threading
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type

from src.utils.exceptions import APIConnectionError
from src.utils.logger import logger


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures.

    The circuit breaker pattern prevents an application from repeatedly
    trying to execute an operation that's likely to fail, allowing it to
    continue without waiting for the fault to be fixed or wasting resources.

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests are rejected immediately
        - HALF_OPEN: Testing if service has recovered

    Example:
        ```
        breaker = CircuitBreaker(failure_threshold=5, timeout=60)

        result = breaker.call(api_function, arg1, arg2)
        ```
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: Type[BaseException] = Exception,
        name: str = "CircuitBreaker",
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting recovery (HALF_OPEN)
            expected_exception: Exception type that counts as failure
            name: Name for logging purposes
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.name = name

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
        # One breaker instance is shared across category nodes that LangGraph
        # runs concurrently in the same superstep -- without this, concurrent
        # `_on_failure()` calls race on `failure_count += 1` (a non-atomic
        # read-modify-write), silently undercounting failures.
        self._lock = threading.Lock()

        logger.info(
            f"CircuitBreaker '{name}' initialized: "
            f"threshold={failure_threshold}, timeout={timeout}s"
        )

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            APIConnectionError: If circuit is OPEN
            Exception: If func raises an exception
        """
        # Check if circuit is OPEN
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info(f"CircuitBreaker '{self.name}': Attempting recovery (HALF_OPEN)")
                    self.state = CircuitState.HALF_OPEN
                else:
                    # Reached only when `_should_attempt_reset()` returned False,
                    # which itself requires `last_failure_time` to be set.
                    assert self.last_failure_time is not None
                    wait_time = self.timeout - (time.time() - self.last_failure_time)
                    logger.warning(
                        f"CircuitBreaker '{self.name}': Circuit is OPEN. "
                        f"Retry in {wait_time:.0f}s"
                    )
                    raise APIConnectionError(
                        f"Circuit breaker is OPEN for {self.name}. "
                        f"Service unavailable. Retry after {wait_time:.0f}s"
                    )

        # Execute function outside the lock -- this is what lets concurrent
        # category nodes actually run in parallel instead of serializing on
        # the breaker.
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except self.expected_exception as e:
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset.

        Returns:
            True if should attempt reset, False otherwise
        """
        if self.last_failure_time is None:
            return True

        return (time.time() - self.last_failure_time) > self.timeout

    def _on_success(self):
        """Handle successful function execution."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info(f"CircuitBreaker '{self.name}': Recovery successful, closing circuit")

            self.failure_count = 0
            self.state = CircuitState.CLOSED

    def _on_failure(self):
        """Handle failed function execution."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            logger.warning(
                f"CircuitBreaker '{self.name}': "
                f"Failure {self.failure_count}/{self.failure_threshold}"
            )

            if self.failure_count >= self.failure_threshold:
                logger.error(f"CircuitBreaker '{self.name}': Threshold reached, opening circuit")
                self.state = CircuitState.OPEN

    def reset(self):
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            logger.info(f"CircuitBreaker '{self.name}': Manual reset")
            self.failure_count = 0
            self.last_failure_time = None
            self.state = CircuitState.CLOSED

    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state.

        Returns:
            Dictionary with current state information
        """
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "last_failure_time": self.last_failure_time,
                "timeout": self.timeout,
            }


def circuit_breaker(
    failure_threshold: int = 5,
    timeout: int = 60,
    expected_exception: Type[BaseException] = Exception,
    name: Optional[str] = None,
):
    """Decorator for applying circuit breaker pattern to functions.

    Args:
        failure_threshold: Number of failures before opening circuit
        timeout: Seconds to wait before attempting recovery
        expected_exception: Exception type that counts as failure
        name: Name for logging (defaults to function name)

    Example:
        ```
        @circuit_breaker(failure_threshold=3, timeout=30)
        def call_external_api():
            # API call logic
            pass
        ```
    """

    def decorator(func: Callable) -> Callable:
        breaker_name = name or f"{func.__module__}.{func.__name__}"
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            timeout=timeout,
            expected_exception=expected_exception,
            name=breaker_name,
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)

        # Attach breaker to wrapper for external access (e.g. tests inspecting
        # state). Functions don't statically declare this attribute, hence
        # the ignore -- this is a standard, deliberate decorator pattern.
        wrapper.circuit_breaker = breaker  # type: ignore[attr-defined]

        return wrapper

    return decorator
