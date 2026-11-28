"""Bounded tool-calling investigator (ReAct loop) for one category.

Built on `langchain.agents.create_agent` (the current API;
`langgraph.prebuilt.create_react_agent` is deprecated since LangGraph 1.0).
The LLM chooses which tools to call, with what arguments, and when it has
enough evidence, then submits structured findings via `response_format`.

Bounds on every investigation:
- tool calls: at most `max_tool_calls` run; further calls are answered with
  BUDGET_SPENT so the agent submits what it has;
- steps: `recursion_limit = max_tool_calls * 2 + 8` (each tool round-trip is
  ~2 graph steps, plus room to wrap up); exhaustion raises `GraphRecursionError`;
- wall clock: `timeout_seconds`, enforced with a daemon thread so a stuck
  provider call can't hang the process at interpreter shutdown;
- prompt size: recon data is trimmed by `summarize_recon_data` (a single
  untrimmed prompt was once observed requesting ~112k tokens).

Failures raise `InvestigationError`; the workflow then falls back to the
category's deterministic shallow result, so a failed deep dive never costs
the report its recon findings.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from drrepo.agents.llm import LLMRuntime, estimate_tokens, extract_actual_tokens
from drrepo.errors import CircuitOpenError, InvestigationError
from drrepo.log import logger
from drrepo.models import Category, Issue, Location, Severity, ToolCallTrace
from drrepo.resilience import is_retryable_llm_error

MAX_LIST_ITEMS_IN_PROMPT = 15
MAX_TEXT_FIELD_CHARS = 1500
MAX_OBSERVATION_CHARS = 600
# Recon fields left out of the prompt: the agent reads these with its tools
# when it needs them, so inlining them only spends tokens.
_OMITTED_FIELDS = frozenset({"readme_content"})
# Retries of one model call in the agent loop, and the longest wait for one.
# Generous on purpose: on a per-minute token limit the window drains in seconds,
# and the investigation's deadline bounds the total wait anyway.
MODEL_CALL_RETRIES = 5
MAX_RETRY_WAIT_SECONDS = 60.0


# Public names on purpose -- see the naming gotcha in planner.py.
class IssueOutput(BaseModel):
    severity: str = Field(description="One of: critical, high, medium, low")
    title: str = Field(description="Short, specific title")
    description: str = Field(description="What is wrong and the evidence you found for it")
    recommendation: str = Field(description="Concrete fix")
    file: str | None = Field(default=None, description="Repo-relative path where the evidence is")
    line: int | None = None
    evidence: str | None = Field(
        default=None,
        description="Optional exact excerpt (one or a few lines) copied from the file that shows the problem",
    )


class InvestigationOutput(BaseModel):
    summary: str = Field(description="3-5 sentence narrative of what you checked and found")
    issues: list[IssueOutput] = Field(default_factory=list)


@dataclass
class InvestigationResult:
    summary: str
    issues: list[Issue]
    trace: list[ToolCallTrace] = field(default_factory=list)
    # issue index -> code excerpt the agent quoted (checked by agents/grounding.py)
    evidence: dict[int, str] = field(default_factory=dict)


def _summarize_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT_FIELD_CHARS:
        return value[:MAX_TEXT_FIELD_CHARS] + f"... [truncated, {len(value)} chars total]"
    if isinstance(value, list):
        kept = [_summarize_value(v) for v in value[:MAX_LIST_ITEMS_IN_PROMPT]]
        if len(value) > MAX_LIST_ITEMS_IN_PROMPT:
            kept.append(f"... and {len(value) - MAX_LIST_ITEMS_IN_PROMPT} more")
        return kept
    if isinstance(value, dict):
        return {k: _summarize_value(v) for k, v in value.items() if k not in _OMITTED_FIELDS}
    return value


def summarize_recon_data(recon_data: dict[str, Any]) -> dict[str, Any]:
    """Bound every long string and list (recursively) before it enters a prompt, and
    drop fields the agent can read itself (the README). The investigator can still
    `read_file`/`search_code` for anything trimmed."""
    return {name: _summarize_value(data) for name, data in recon_data.items()}


_STATUS_REASONS = {
    400: "the provider rejected the request",
    401: "the provider rejected the API key",
    403: "the provider refused access",
    404: "the provider doesn't offer this model",
    413: "the request is larger than the provider's per-request limit",
    429: "rate limited by the provider",
}


def describe_llm_error(error: BaseException) -> str:
    """A short, shareable reason for a failed LLM call. Reports end up in pull requests,
    so the provider's raw message (account and organization ids) stays in the log."""
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int):
        reason = _STATUS_REASONS.get(status, "the provider failed")
        if status == 429 and "per day" in str(error).lower():
            reason = "the provider's daily quota is used up"
        return f"{type(error).__name__} (HTTP {status}): {reason}"
    return f"{type(error).__name__}: {str(error)[:200]}"


def retry_after_seconds(error: BaseException) -> float | None:
    """The provider's `retry-after` hint on a rate-limit error, in seconds, if it gave one."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _model_retry_middleware(deadline: float | None) -> Any:
    """Retry each model call in the agent loop like every other LLM call: rate limits
    and 5xx back off, permanent errors fail at once. A provider's `retry-after`
    is honored when it fits in the investigation's remaining time."""
    from langchain.agents.middleware import AgentMiddleware
    from langgraph.errors import GraphBubbleUp

    class ProviderRetry(AgentMiddleware):
        def wrap_model_call(self, request: Any, handler: Any) -> Any:
            for attempt in range(MODEL_CALL_RETRIES + 1):
                try:
                    return handler(request)
                except GraphBubbleUp:
                    raise
                except Exception as error:
                    if attempt == MODEL_CALL_RETRIES or not is_retryable_llm_error(error):
                        raise
                    hinted = retry_after_seconds(error)
                    if hinted is not None and hinted > MAX_RETRY_WAIT_SECONDS:
                        raise  # the provider asks for a longer wait than is worth it
                    delay = min(
                        MAX_RETRY_WAIT_SECONDS,
                        hinted if hinted is not None else 2.0 * 2**attempt,
                    )
                    if deadline is not None and time.monotonic() + delay >= deadline:
                        raise  # waiting would outlast the investigation's time budget
                    logger.info(
                        f"model call failed ({type(error).__name__}); retrying in {delay:.0f}s"
                    )
                    time.sleep(delay)
            raise AssertionError("unreachable")  # pragma: no cover

    return ProviderRetry()


def build_prompt(
    recon_data: dict[str, Any], known_issues: list[Issue], user_context: str = ""
) -> str:
    known = (
        "\n".join(
            f"- [{i.severity.value}] {i.title} ({i.file or 'n/a'})" for i in known_issues[:25]
        )
        or "- none"
    )
    # Compact JSON: indentation would cost about a quarter more tokens.
    recon = json.dumps(summarize_recon_data(recon_data), separators=(",", ":"), default=str)
    return (
        "Recon data already collected for this repository (trimmed):\n"
        f"{recon}\n\n"
        f"Issues already reported by automated tools (do not repeat these):\n{known}\n\n"
        + (f"User context: {user_context.strip()}\n\n" if user_context.strip() else "")
        + "Investigate using the tools available. Only call tools that are useful, and stop once "
        "you have enough evidence. Report only NEW issues you verified with a tool; cite the file. "
        "If you find nothing new, return an empty issue list -- that is a valid outcome."
    )


# The conversation never gets less than this, however small the cap.
MIN_MESSAGE_TOKENS = 1500
# Answer to a tool call over the budget: the agent then submits what it has
# instead of the run ending with nothing (a GraphRecursionError).
BUDGET_SPENT = (
    "ERROR: the tool-call budget is used up. Call no more tools: submit your findings now."
)
# Model turns left after the budget is spent, to read that answer and submit.
_WRAP_UP_STEPS = 4


def _tool_budget_middleware(max_tool_calls: int) -> Any:
    """Run at most `max_tool_calls` real tool calls; answer any further call with
    BUDGET_SPENT, so the agent concludes with the evidence it has."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import ToolMessage

    class ToolBudget(AgentMiddleware):
        def __init__(self) -> None:
            super().__init__()
            self._used = 0
            self._lock = threading.Lock()

        def wrap_tool_call(self, request: Any, handler: Any) -> Any:
            with self._lock:
                allowed = self._used < max_tool_calls
                self._used += allowed
            if allowed:
                return handler(request)
            call = request.tool_call
            return ToolMessage(
                content=BUDGET_SPENT, tool_call_id=call.get("id") or "", name=call.get("name")
            )

    return ToolBudget()


def _fixed_tokens(system_prompt: str, tools: list[Any]) -> int:
    """Tokens every request spends before the conversation: system prompt and tool schemas."""
    schemas = [
        {"name": t.name, "description": t.description, "args": getattr(t, "args", {})}
        for t in tools
    ]
    return estimate_tokens(system_prompt) + estimate_tokens(json.dumps(schemas, default=str))


def _context_middleware(message_tokens: int) -> list[Any]:
    """Keep the conversation under `message_tokens`: clear older tool results, and cut
    any one result to a third of the budget (the agent can read a narrower range)."""
    from langchain.agents.middleware import (
        AgentMiddleware,
        ClearToolUsesEdit,
        ContextEditingMiddleware,
    )
    from langchain_core.messages import ToolMessage

    budget = max(MIN_MESSAGE_TOKENS, message_tokens)
    max_chars = budget * 4 // 3  # ~4 characters per token, a third of the budget

    class ToolOutputCap(AgentMiddleware):
        def wrap_tool_call(self, request: Any, handler: Any) -> Any:
            result = handler(request)
            content = getattr(result, "content", None)
            if (
                isinstance(result, ToolMessage)
                and isinstance(content, str)
                and len(content) > max_chars
            ):
                result.content = (
                    content[:max_chars] + f"\n[truncated at {max_chars} of {len(content)} "
                    "characters to fit the token budget; request a narrower range]"
                )
            return result

    return [
        ToolOutputCap(),
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=budget,
                    keep=1,
                    placeholder="[cleared to save tokens; call the tool again if needed]",
                )
            ]
        ),
    ]


def investigate(
    *,
    category: Category,
    system_prompt: str,
    tools: list[Any],
    llm: LLMRuntime,
    recon_data: dict[str, Any],
    known_issues: list[Issue],
    max_tool_calls: int,
    timeout_seconds: float | None = None,
    user_context: str = "",
    context_tokens: int | None = None,
    reserve_tokens: int = 0,
) -> InvestigationResult:
    """Run one bounded investigation. Raises `InvestigationError` on any failure.

    `context_tokens` caps one model request: the system prompt, tool schemas
    and conversation, plus `reserve_tokens` for the reply (MAX_TOKENS). Older
    tool results are cleared to stay under it, and each new result is cut to a
    share of it, so a long tool loop fits a provider's per-request limit."""
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy

    deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
    prompt = build_prompt(recon_data, known_issues, user_context)
    middleware: list[Any] = [
        _model_retry_middleware(deadline),
        _tool_budget_middleware(max_tool_calls),
    ]
    if context_tokens:
        middleware += _context_middleware(
            context_tokens - reserve_tokens - _fixed_tokens(system_prompt, tools)
        )

    agent = create_agent(
        model=llm.client,
        tools=tools,
        system_prompt=system_prompt,
        # Always submit findings as a tool call. With a bare schema, models with
        # native structured output get a JSON response_format alongside the tools,
        # which providers such as Groq reject ("json mode cannot be combined with
        # tool/function calling").
        response_format=ToolStrategy(InvestigationOutput),
        middleware=middleware,
    )
    # Two graph steps per tool round trip, plus room to wrap up once the budget is spent.
    recursion_limit = max_tool_calls * 2 + 4 + _WRAP_UP_STEPS

    def _invoke() -> Any:
        return agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"recursion_limit": recursion_limit},
        )

    try:
        result = _run_with_timeout(lambda: llm.guarded(_invoke), timeout_seconds)
    except TimeoutError as e:
        raise InvestigationError(
            f"stopped after exceeding its {timeout_seconds:.0f}s time budget"
        ) from e
    except GraphRecursionError as e:
        raise InvestigationError(
            f"reached its {max_tool_calls}-tool-call budget before concluding"
        ) from e
    except CircuitOpenError as e:
        raise InvestigationError(
            "skipped: the LLM circuit breaker is open (provider failing or quota exhausted)"
        ) from e
    except Exception as e:
        logger.error(f"Investigator for {category.value} failed: {e}")
        raise InvestigationError(f"failed: {describe_llm_error(e)}") from e

    messages = result.get("messages", [])
    if llm.budget is not None:
        llm.budget.record(estimate_run_tokens(prompt, messages), llm.label)

    structured = result.get("structured_response")
    if not isinstance(structured, InvestigationOutput):
        raise InvestigationError("finished without submitting structured findings")

    reported = [item for item in structured.issues if item.title.strip()]
    issues = [
        Issue(
            severity=Severity.parse(item.severity),
            category=category,
            title=item.title.strip()[:160],
            description=item.description.strip(),
            recommendation=item.recommendation.strip(),
            source=f"investigator:{category.value}",
            rule_id="agent-finding",
            locations=[Location(file=item.file.strip().removeprefix("./"), line=item.line)]
            if item.file
            else [],
        )
        for item in reported
    ]
    return InvestigationResult(
        summary=structured.summary.strip(),
        issues=issues,
        trace=extract_trace(messages),
        evidence={i: item.evidence for i, item in enumerate(reported) if item.evidence},
    )


def _run_with_timeout(func: Any, timeout_seconds: float | None) -> Any:
    """Run `func` on a daemon thread, raising TimeoutError if it overruns.

    Deliberately not `ThreadPoolExecutor`: its workers are non-daemon and its
    atexit hook joins them, so a stuck call would hang interpreter shutdown.
    An abandoned daemon thread is simply killed at process exit.
    """
    if timeout_seconds is None:
        return func()
    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["result"] = func()
        except BaseException as e:  # re-raised on the caller's thread below
            outcome["error"] = e

    thread = threading.Thread(target=_target, daemon=True, name="drrepo-investigator")
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        raise TimeoutError(f"investigation exceeded {timeout_seconds}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def estimate_run_tokens(prompt: str, messages: list[Any]) -> int:
    """Total tokens for one investigation. Each agent turn is its own request,
    billed for its full context, so summing per-message usage is correct."""
    total = estimate_tokens(prompt)
    for msg in messages:
        tokens = extract_actual_tokens(msg)
        total += tokens if tokens is not None else estimate_tokens(str(getattr(msg, "content", "")))
    return total


def extract_trace(messages: list[Any]) -> list[ToolCallTrace]:
    """(tool, input, observation) triples from the agent's message history.

    `create_agent` submits structured output as a synthetic tool call named
    after the response-format class; that's the answer, not an investigation
    step, so it is excluded.
    """
    trace: list[ToolCallTrace] = []
    pending: dict[str, tuple[str, dict[str, Any]]] = {}
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            if call.get("name") == InvestigationOutput.__name__:
                continue
            pending[call.get("id") or ""] = (call.get("name", "?"), call.get("args") or {})
        call_id = getattr(msg, "tool_call_id", None)
        if type(msg).__name__ == "ToolMessage" and call_id in pending:
            tool, tool_input = pending.pop(call_id)
            if msg.content == BUDGET_SPENT:
                continue  # refused over budget: never ran
            trace.append(
                ToolCallTrace(
                    tool=tool,
                    tool_input=tool_input,
                    observation=str(msg.content)[:MAX_OBSERVATION_CHARS],
                )
            )
    return trace
