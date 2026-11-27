"""Custom exceptions for DrRepo.

Kept deliberately small: only exceptions something in the codebase actually
raises or catches live here.
"""

from __future__ import annotations


class DrRepoError(Exception):
    """Base class for every DrRepo-specific error."""


class CircuitOpenError(DrRepoError):
    """Raised by `CircuitBreaker.call` when the circuit is open.

    Callers treat this as "the LLM provider is known to be failing right
    now" and fall back to deterministic output instead of retrying.
    """


class ConfigurationError(DrRepoError):
    """Raised when configuration values are present but invalid."""
