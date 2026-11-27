"""Every exception DrRepo raises on purpose. Catch `DrRepoError` to handle them all."""

from __future__ import annotations


class DrRepoError(Exception):
    """Base class for DrRepo-specific errors."""


class ConfigurationError(DrRepoError):
    """A configuration value is present but invalid."""


class CircuitOpenError(DrRepoError):
    """`CircuitBreaker.call` refused to run because the circuit is open.

    Treated as "the LLM provider is known to be failing right now": callers fall
    back to deterministic output instead of retrying.
    """


class InvestigationError(DrRepoError):
    """A deep investigation produced no result. `reason` is user-presentable and
    completes the sentence "Deep investigation ..."."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
