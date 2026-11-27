"""Thread-safe, per-run LLM token budget.

Token counts are approximate: real usage is read from provider response
metadata when present (`usage_metadata` / `response_metadata.token_usage`),
otherwise estimated at ~4 characters per token.

The budget exists to make the planner's shallow/deep decisions cost-aware:
`Workflow` reserves budget for each deep investigation *before* fanning out to
the parallel category nodes, so five nodes can't all see a full budget at the
same instant and all go deep. Built after a live Groq 413 "tokens per day"
failure (see docs/architecture.md).
"""

from __future__ import annotations

import threading
from typing import Any

_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimate for text that hasn't been sent to the LLM yet."""
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def extract_actual_tokens(response: Any) -> int | None:
    """Real total-token usage from an LLM response, or None if not reported.

    Returns None -- not 0 -- when absent, so callers fall back to an estimate.
    The `isinstance(..., dict)` checks are load-bearing: a plain
    `unittest.mock.Mock()` auto-vivifies attributes, so without them an
    unconfigured test double reads as "usage present" and then crashes.
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage.get("total_tokens"):
        return int(usage["total_tokens"])

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, dict) and token_usage.get("total_tokens"):
            return int(token_usage["total_tokens"])

    return None


class LLMBudgetTracker:
    """Accumulates token usage for one workflow run. Safe to share across threads."""

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self._used = 0
        self._lock = threading.Lock()

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_tokens - self._used)

    def has_budget_for(self, estimated_tokens: int) -> bool:
        return self.remaining() >= estimated_tokens

    def affordable_count(self, cost_each: int) -> int:
        """How many operations of `cost_each` tokens the remaining budget covers."""
        if cost_each <= 0:
            return 0
        return self.remaining() // cost_each

    def record(self, tokens: int) -> None:
        """Add to the running total. Zero/negative values are ignored."""
        if tokens <= 0:
            return
        with self._lock:
            self._used += tokens

    def reset(self) -> None:
        """Zero the running total. `Workflow.execute` calls this at the start of
        every run, since the cap is per run, not per tracker lifetime."""
        with self._lock:
            self._used = 0

    def usage(self) -> dict[str, int]:
        with self._lock:
            return {
                "used_tokens": self._used,
                "max_tokens": self.max_tokens,
                "remaining_tokens": max(0, self.max_tokens - self._used),
            }
