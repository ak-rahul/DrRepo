"""Retry decorator with exponential backoff for transient failures."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from drrepo.core.log import logger

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[BaseException], bool] | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> Callable[[F], F]:
    """Retry the decorated function with exponential backoff.

    Args:
        max_retries: Retries after the first attempt (so up to `max_retries + 1` calls).
        backoff_factor: Multiplier applied to the delay after each failed attempt.
        initial_delay: Delay before the first retry, in seconds.
        max_delay: Upper bound on any single delay, in seconds.
        exceptions: Exception types that are eligible for a retry.
        should_retry: Optional predicate; returning False re-raises immediately.
            Use it to skip retries on errors that can't succeed on a second
            try (bad credentials, 404s) instead of sleeping through backoff.
        on_retry: Optional callback `(attempt, exception, wait_seconds)`.

    With the defaults the schedule is: call, wait 1s, call, wait 2s, call, wait 4s, call.
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

                    wait_time = min(initial_delay * (backoff_factor**attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e, wait_time)
                        except Exception as callback_error:
                            logger.error(f"Retry callback failed: {callback_error}")
                    time.sleep(wait_time)
                else:
                    if attempt > 0:
                        logger.info(
                            f"{func.__name__} succeeded on attempt {attempt + 1}/{max_retries + 1}"
                        )
                    return result
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper  # type: ignore[return-value]

    return decorator


def is_retryable_llm_error(error: BaseException) -> bool:
    """Return False for LLM errors that will fail identically on every retry.

    Authentication/permission/bad-request errors (HTTP 400/401/403/404) are
    permanent for the life of a run; retrying them just burns the full backoff
    schedule. Rate limits (429) and server errors (5xx) are worth retrying.
    Detection is duck-typed on `status_code` so it works for both the Groq and
    OpenAI SDK exception hierarchies without importing either.
    """
    from drrepo.core.errors import CircuitOpenError

    if isinstance(error, CircuitOpenError):
        return False
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    return not (isinstance(status, int) and status in (400, 401, 403, 404, 413, 422))
