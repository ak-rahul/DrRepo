"""LLM client construction, the per-run token budget, and the one guarded call
path every agent uses.

`LLMRuntime` bundles the chat model with the run's circuit breaker and token
budget, so each call site doesn't re-implement "retry, but not past an open
breaker, and record usage". Layering (load-bearing, see docs/architecture.md):

    breaker.call( retry_with_backoff( client.invoke ) )

The breaker wraps the retry loop, not the other way around: retries absorb a
single transient blip inside one logical call, while the breaker stops *new*
logical calls once failures are sustained. Nesting retry outside the breaker
would make every attempt pay full backoff against an already-open circuit.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from drrepo.config import Config
from drrepo.errors import ConfigurationError
from drrepo.resilience import CircuitBreaker, is_retryable_llm_error, retry_with_backoff

# -------------------------------------------------------------- budget ---
# Token counts are approximate: real usage is read from provider metadata when
# present, otherwise estimated at ~4 characters per token. The budget makes
# shallow/deep planning cost-aware; the pipeline reserves it *before* the
# parallel fan-out (see pipeline.py). Built after a live Groq 413 "tokens per
# day" failure.

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


class TokenBudget:
    """Accumulates token usage for one workflow run. Safe to share across threads.

    Usage is also kept per label ("planner", "critic", "investigation:security",
    ...), so a report shows where the tokens went and the next run can size its
    deep investigations from what they really cost (see `report.history`).
    """

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self._used = 0
        self._by_label: dict[str, int] = {}
        self._lock = threading.Lock()

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_tokens - self._used)

    def affordable_count(self, cost_each: int) -> int:
        """How many operations of `cost_each` tokens the remaining budget covers."""
        if cost_each <= 0:
            return 0
        return self.remaining() // cost_each

    def record(self, tokens: int, label: str = "other") -> None:
        """Add to the running total and to `label`'s line. Zero/negative values are ignored."""
        if tokens <= 0:
            return
        with self._lock:
            self._used += tokens
            self._by_label[label] = self._by_label.get(label, 0) + tokens

    def used_by(self, label: str) -> int:
        with self._lock:
            return self._by_label.get(label, 0)

    def reset(self) -> None:
        """Zero the running total. Runs never share a budget (`AnalysisService`
        builds a fresh one per run), so this is only for reusing an instance."""
        with self._lock:
            self._used = 0
            self._by_label.clear()

    def usage(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used_tokens": self._used,
                "max_tokens": self.max_tokens,
                "remaining_tokens": max(0, self.max_tokens - self._used),
                "by_label": dict(sorted(self._by_label.items())),
            }


# -------------------------------------------------------------- client ---


def _optional_import(module: str, extra: str) -> Any:
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise ConfigurationError(
            f"MODEL_PROVIDER needs the optional '{extra}' extra: uv sync --extra {extra} "
            f"(or pip install 'drrepo[{extra}]')"
        ) from e


def build_chat_model(config: Config, model: str | None = None) -> Any:
    """Construct the LangChain chat model for the configured provider.

    `model` defaults to `config.model_for()`. SDK retries are always off: retries
    are ours (`retry_with_backoff`), layered inside the circuit breaker.
    """
    from pydantic import SecretStr

    model = model or config.model_for()
    if config.model_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,  # retries are ours (see retry_with_backoff), not the SDK's
            api_key=SecretStr(config.groq_api_key),
        )
    if config.model_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=config.temperature,
            max_completion_tokens=config.max_tokens,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,
            api_key=SecretStr(config.openai_api_key),
        )
    if config.model_provider == "anthropic":
        anthropic = _optional_import("langchain_anthropic", "anthropic")
        return anthropic.ChatAnthropic(
            model=model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,
            api_key=SecretStr(config.anthropic_api_key),
        )
    if config.model_provider == "ollama":
        ollama = _optional_import("langchain_ollama", "ollama")
        return ollama.ChatOllama(
            model=model,
            temperature=config.temperature,
            num_predict=config.max_tokens,
            base_url=config.ollama_base_url,
            client_kwargs={"timeout": config.llm_request_timeout_seconds},
        )
    # Unreachable: Config.__post_init__ rejects unknown providers.
    raise ValueError(f"Unsupported model provider: {config.model_provider!r}")  # pragma: no cover


@retry_with_backoff(
    max_retries=2, initial_delay=2.0, max_delay=20.0, should_retry=is_retryable_llm_error
)
def _invoke_with_retry(runnable: Any, messages: Any) -> Any:
    return runnable.invoke(messages)


@dataclass
class LLMRuntime:
    """The chat model plus the run's shared breaker and budget (either may be None)."""

    client: Any  # None means "no LLM configured": callers skip LLM work entirely
    breaker: CircuitBreaker | None = None
    budget: TokenBudget | None = None
    # Optional per-role clients (config.LLM_ROLES); roles without one use `client`.
    role_clients: dict[str, Any] = field(default_factory=dict)
    # The budget line this runtime's usage is recorded under.
    label: str = "other"

    @property
    def available(self) -> bool:
        return self.client is not None

    def for_role(self, role: str, label: str | None = None) -> LLMRuntime:
        """The runtime for one role, recording usage under `label` (default: the role).

        It shares this run's breaker and budget, so routing roles to different
        models can't hide an outage or double the spend.
        """
        return LLMRuntime(
            client=self.role_clients.get(role, self.client),
            breaker=self.breaker,
            budget=self.budget,
            label=label or role,
        )

    def guarded(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run `func` under the circuit breaker (if any)."""
        if self.breaker is None:
            return func(*args, **kwargs)
        return self.breaker.call(func, *args, **kwargs)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """One system+user chat completion; returns the text content.

        Raises whatever the provider raised (after retries), or
        `CircuitOpenError` if the breaker is open.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        response = self.guarded(_invoke_with_retry, self.client, messages)
        content = str(getattr(response, "content", response))
        self.record_usage(response, system_prompt + user_prompt + content)
        return content.strip()

    def structured(self, schema: type, system_prompt: str, user_prompt: str) -> Any:
        """A structured-output call returning an instance of the pydantic `schema`."""
        from langchain_core.messages import HumanMessage, SystemMessage

        runnable = self.client.with_structured_output(schema)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        result = self.guarded(_invoke_with_retry, runnable, messages)
        # Parsed pydantic objects carry no usage metadata -- always an estimate.
        self.record_usage(None, system_prompt + user_prompt + str(result))
        return result

    def record_usage(self, response: Any, fallback_text: str) -> None:
        if self.budget is None:
            return
        tokens = extract_actual_tokens(response) if response is not None else None
        self.budget.record(
            tokens if tokens is not None else estimate_tokens(fallback_text), self.label
        )
