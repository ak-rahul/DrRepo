"""Base class for LLM-based analyst agents.

Unlike v1's `BaseAgent`, the LLM client is constructed once by the caller and
injected here -- never built from a global config singleton. This is what
makes agents testable with a fake/mock client and no environment coupling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Protocol

from src.config import Config
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker, estimate_tokens, extract_actual_tokens
from src.utils.logger import logger
from src.utils.retry import retry_with_backoff


class LLMClient(Protocol):
    """Structural type for whatever chat-model client is injected.

    Anything with an `.invoke(...) -> response` method (LangChain chat
    models, or a test double) satisfies this. Deliberately loose (`*args,
    **kwargs`) rather than mirroring LangChain's exact `Runnable.invoke`
    signature, which mypy otherwise can't structurally match against a
    `Protocol` due to unrelated parameter names/overloads.
    """

    def invoke(self, *args: Any, **kwargs: Any) -> Any: ...


def build_llm_client(config: Config) -> LLMClient:
    """Construct the real LangChain chat client for the configured provider.

    Call this once at a real entrypoint and pass the result into each agent's
    constructor -- agents themselves never call this.
    """
    from pydantic import SecretStr

    if config.model_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=config.model_name,
            temperature=config.temperature,
            api_key=SecretStr(config.groq_api_key),
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,  # type: ignore[call-arg]  # accepted at runtime; missing from stub
        api_key=SecretStr(config.openai_api_key),
    )


class BaseAnalystAgent(ABC):
    """Abstract base for analyst agents that turn collector findings into a
    narrative + issue list for one report category."""

    name: str
    system_prompt: str

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm_client: LLMClient,
        llm_breaker: Optional[CircuitBreaker] = None,
        llm_budget: Optional[LLMBudgetTracker] = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.llm_breaker = llm_breaker
        self.llm_budget = llm_budget

    @abstractmethod
    def analyze(self, collector_results: dict[str, Any]) -> dict[str, Any]:
        """Return `{"summary": str, "score": float, "issues": [Issue-as-dict]}`."""
        raise NotImplementedError

    def _call_llm(self, user_prompt: str) -> str:
        """Call the LLM, guarded by the circuit breaker (if configured) and
        recording token usage against the budget tracker (if configured).

        The breaker check happens *outside* `_invoke_with_retry`'s retry loop
        deliberately: retries handle transient failures within one logical
        call (a single network blip), while the breaker guards against
        sustained failure across many logical calls (e.g. a provider's daily
        quota being exhausted). Nesting them the other way around would make
        every retry attempt re-check an already-open breaker and still pay
        the full exponential backoff sleep between them for no benefit.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=self.system_prompt), HumanMessage(content=user_prompt)]

        try:
            response = (
                self.llm_breaker.call(self._invoke_with_retry, messages)
                if self.llm_breaker
                else self._invoke_with_retry(messages)
            )
        except Exception as e:
            logger.error(f"LLM call failed in {self.name}: {e}")
            raise

        if self.llm_budget is not None:
            tokens = extract_actual_tokens(response)
            if tokens is None:
                tokens = estimate_tokens(self.system_prompt + user_prompt + str(response.content))
            self.llm_budget.record(tokens)

        return str(response.content)

    @retry_with_backoff(max_retries=3, initial_delay=2.0, max_delay=30.0)
    def _invoke_with_retry(self, messages: list) -> Any:
        return self.llm_client.invoke(messages)
