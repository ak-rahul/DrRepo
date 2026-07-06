"""Thread-safe LLM token budget tracker shared across one workflow run.

Token counts are approximate: real usage is extracted from provider response
metadata when available (LangChain chat models expose `usage_metadata` on
`AIMessage`/response objects), falling back to a character-count heuristic
(~4 chars/token, a standard rough estimate for English text) when it isn't --
e.g. for the pre-call affordability check, or test doubles that don't set
usage_metadata.

This exists to make the planner's shallow/deep decisions cost-aware: a repo
signal might warrant a deep investigation, but if the run has already spent
most of its budget on earlier categories (running in parallel), later
categories fall back to shallow rather than risk exhausting a real API quota
mid-run -- this was built in direct response to a live Groq 413 "tokens per
day" failure hit during manual testing (see CLAUDE.md).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimate for text that hasn't been sent to the LLM yet."""
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def extract_actual_tokens(response: Any) -> Optional[int]:
    """Pull real total-token usage off an LLM response, if the provider reported it.

    Checks both places LangChain chat models are known to surface it:
    `response.usage_metadata["total_tokens"]` (newer, provider-agnostic) and
    `response.response_metadata["token_usage"]["total_tokens"]` (older/Groq
    style). Returns None -- not 0 -- when neither is present, so callers can
    fall back to an estimate instead of recording a false "0 tokens used".

    The `isinstance(..., dict)` checks are load-bearing, not defensive
    boilerplate: a plain `unittest.mock.Mock()` (not `MagicMock`/`spec=`)
    auto-vivifies any attribute access, so `response.usage_metadata` on an
    unconfigured test double returns a truthy Mock whose `.get(...)` call
    also auto-vivifies a truthy Mock -- without the `isinstance` guard this
    reads as "usage metadata present" and then crashes subscripting it
    (confirmed by a real workflow-test failure during development).
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
    """Tracks approximate/actual token usage across one workflow run.

    Thread-safe: category nodes run in parallel in the LangGraph workflow, so
    `record()`/`has_budget_for()` can be called concurrently from multiple
    threads against the same tracker instance.
    """

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self._used = 0
        self._lock = threading.Lock()

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_tokens - self._used)

    def has_budget_for(self, estimated_tokens: int) -> bool:
        return self.remaining() >= estimated_tokens

    def record(self, tokens: int) -> None:
        """Add to the running total. Negative/zero values are ignored."""
        if tokens <= 0:
            return
        with self._lock:
            self._used += tokens

    def usage(self) -> Dict[str, int]:
        with self._lock:
            return {
                "used_tokens": self._used,
                "max_tokens": self.max_tokens,
                "remaining_tokens": max(0, self.max_tokens - self._used),
            }
