"""LLM client construction and the one guarded call path every agent uses.

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

from dataclasses import dataclass
from typing import Any

from drrepo.config import Config
from drrepo.core.budget import LLMBudgetTracker, estimate_tokens, extract_actual_tokens
from drrepo.core.circuit_breaker import CircuitBreaker
from drrepo.core.retry import is_retryable_llm_error, retry_with_backoff


def build_chat_model(config: Config) -> Any:
    """Construct the LangChain chat model for the configured provider."""
    from pydantic import SecretStr

    if config.model_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,  # retries are ours (see retry_with_backoff), not the SDK's
            api_key=SecretStr(config.groq_api_key),
        )
    if config.model_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model_name,
            temperature=config.temperature,
            max_completion_tokens=config.max_tokens,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,
            api_key=SecretStr(config.openai_api_key),
        )
    raise ValueError(f"Unsupported model provider: {config.model_provider!r}")


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
    budget: LLMBudgetTracker | None = None

    @property
    def available(self) -> bool:
        return self.client is not None

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
        self.budget.record(tokens if tokens is not None else estimate_tokens(fallback_text))
