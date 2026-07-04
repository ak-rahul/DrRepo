"""Utilities for DrRepo. Deliberately lightweight - no eager heavy imports."""

from src.utils.circuit_breaker import CircuitBreaker, CircuitState, circuit_breaker
from src.utils.exceptions import (
    AgentExecutionError,
    AnalysisError,
    APIConnectionError,
    ConfigurationError,
    DrRepoException,
    RateLimitError,
    RepositoryNotFoundError,
    ToolExecutionError,
    ValidationError,
)
from src.utils.logger import logger, setup_logger
from src.utils.retry import retry_on_network_error, retry_on_rate_limit, retry_with_backoff

__all__ = [
    # Logging
    "logger",
    "setup_logger",
    # Retry
    "retry_with_backoff",
    "retry_on_rate_limit",
    "retry_on_network_error",
    # Exceptions
    "DrRepoException",
    "APIConnectionError",
    "ConfigurationError",
    "RepositoryNotFoundError",
    "RateLimitError",
    "AnalysisError",
    "ValidationError",
    "ToolExecutionError",
    "AgentExecutionError",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "circuit_breaker",
]
