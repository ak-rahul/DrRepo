"""Generic tool-calling investigator agent factory.

Built on `langchain.agents.create_agent` (the current, non-deprecated
tool-calling agent API -- `langgraph.prebuilt.create_react_agent` was moved
here in LangGraph 1.0 and is slated for removal in 2.0). Given a category,
its tool subset, and a system prompt, this produces a bounded
think-act-observe loop that decides for itself what evidence to gather, then
emits structured findings via `response_format`.

This is the piece that makes v3 genuinely agentic: the LLM chooses which
tools to call, with what arguments, and in what order, until it decides it
has enough evidence -- unlike the shallow analysts, which make exactly one
fixed call over pre-packaged data.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from src.models import Category
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.exceptions import APIConnectionError
from src.utils.llm_budget import LLMBudgetTracker, estimate_tokens, extract_actual_tokens
from src.utils.logger import logger

_VALID_SEVERITIES = {"critical", "high", "medium", "low"}

# Raw collector data can include a full README dump and long finding lists;
# stuffed directly into a prompt this can balloon to 100k+ tokens for a repo
# with many static-analysis findings (confirmed live against Groq: a single
# request asked for ~112k tokens against a 100k/day quota -- see CLAUDE.md).
# Investigators have file/search tools to pull more detail themselves, so the
# prompt only needs a bounded overview, not everything.
_MAX_LIST_ITEMS_IN_PROMPT = 15
_MAX_TEXT_FIELD_CHARS = 1500


def _summarize_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_TEXT_FIELD_CHARS:
        return value[:_MAX_TEXT_FIELD_CHARS] + f"... [truncated, {len(value)} chars total]"
    if isinstance(value, list):
        if len(value) > _MAX_LIST_ITEMS_IN_PROMPT:
            kept = [_summarize_value(v) for v in value[:_MAX_LIST_ITEMS_IN_PROMPT]]
            return kept + [f"... and {len(value) - _MAX_LIST_ITEMS_IN_PROMPT} more"]
        return [_summarize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _summarize_value(v) for k, v in value.items()}
    return value


def summarize_recon_data(recon_data: Dict[str, Any]) -> Dict[str, Any]:
    """Shrink recon_data before it goes into an investigator's prompt.

    Bounds every long text field and every long list (recursively, through
    nested collector dicts) so a single investigation prompt stays a bounded
    size regardless of how much a repo's static analysis/README/dependency
    data adds up to.
    """
    return {name: _summarize_value(data) for name, data in recon_data.items()}


class IssueOutput(BaseModel):
    severity: str = Field(description="One of: critical, high, medium, low")
    title: str
    description: str
    recommendation: str
    file: Optional[str] = None
    line: Optional[int] = None


class InvestigationOutput(BaseModel):
    summary: str = Field(description="2-5 sentence narrative of what was found and why")
    score: float = Field(description="0-100 score for this category; 100 = no issues found")
    issues: List[IssueOutput] = Field(default_factory=list)


def investigate(
    *,
    category: Category,
    system_prompt: str,
    tools: List[Any],
    llm_client: Any,
    recon_data: Dict[str, Any],
    max_tool_calls: int,
    timeout_seconds: Optional[float] = None,
    llm_breaker: Optional[CircuitBreaker] = None,
    llm_budget: Optional[LLMBudgetTracker] = None,
) -> Dict[str, Any]:
    """Run a bounded tool-calling investigation for one category.

    Returns the same `{"summary", "score", "issues"}` shape the shallow
    analysts produce, plus `investigation_depth`/`investigation_trace`, so the
    synthesizer treats both paths identically.
    """
    agent = create_agent(
        model=llm_client,
        tools=tools,
        system_prompt=system_prompt,
        response_format=InvestigationOutput,
    )

    prompt = (
        f"Initial recon data already collected for this repository:\n"
        f"{summarize_recon_data(recon_data)}\n\n"
        "Investigate this category using the tools available to you. Only call tools that "
        "are actually useful -- stop and give your final findings once you have enough evidence. "
        "Only report issues you found real evidence for through the tools; do not invent findings."
    )

    # Each tool round-trip costs ~2 graph steps (an AI message requesting the
    # call, then the tool's response); pad generously so genuine
    # investigation isn't cut short, while still bounding runaway loops.
    recursion_limit = max_tool_calls * 2 + 4

    def _invoke() -> Any:
        # The ("user", prompt) shorthand is a real, documented LangChain
        # convenience accepted at runtime (verified live against Groq), but
        # narrower than what create_agent's strict overloads declare.
        return agent.invoke(
            {"messages": [("user", prompt)]},  # type: ignore[call-overload]
            config={"recursion_limit": recursion_limit},
        )

    def _invoke_with_breaker() -> Any:
        return llm_breaker.call(_invoke) if llm_breaker else _invoke()

    try:
        if timeout_seconds is None:
            result = _invoke_with_breaker()
        else:
            # A plain daemon thread, not `concurrent.futures.ThreadPoolExecutor`:
            # the executor's worker threads are non-daemon and it registers an
            # `atexit` hook that joins every outstanding one, so a stuck call
            # would hang the whole process at interpreter shutdown even after
            # `shutdown(wait=False)` -- exactly what this timeout exists to
            # avoid. A daemon thread is simply abandoned (and killed) at
            # process exit instead, with no such hook to block on.
            outcome: Dict[str, Any] = {}

            def _run() -> None:
                try:
                    outcome["result"] = _invoke_with_breaker()
                except (
                    BaseException
                ) as e:  # noqa: BLE001 -- re-raised below, on the caller's thread
                    outcome["error"] = e

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            thread.join(timeout=timeout_seconds)
            if thread.is_alive():
                raise TimeoutError(f"investigation exceeded its {timeout_seconds}s time budget")
            if "error" in outcome:
                raise outcome["error"]
            result = outcome["result"]
    except TimeoutError:
        logger.warning(
            f"Investigator for {category.value} exceeded its {timeout_seconds}s time budget"
        )
        return _fallback_result(
            f"Investigation stopped after exceeding its {timeout_seconds}s time budget."
        )
    except GraphRecursionError:
        logger.warning(
            f"Investigator for {category.value} hit its step limit ({max_tool_calls} tool calls)"
        )
        return _fallback_result(
            "Investigation stopped after reaching its tool-call budget before concluding."
        )
    except APIConnectionError as e:
        logger.warning(f"Investigator for {category.value} skipped, circuit breaker open: {e}")
        return _fallback_result(
            "Deep investigation skipped: LLM circuit breaker is open (likely an exhausted "
            "quota from earlier in this run)."
        )
    except Exception as e:
        logger.error(f"Investigator for {category.value} failed: {e}")
        return _fallback_result(f"Deep investigation failed: {e}")

    if llm_budget is not None:
        llm_budget.record(_estimate_run_tokens(prompt, result["messages"]))

    structured: InvestigationOutput = result["structured_response"]
    trace = _extract_trace(result["messages"])

    return {
        "summary": structured.summary,
        "score": max(0.0, min(100.0, structured.score)),
        "issues": [
            {
                "severity": _normalize_severity(issue.severity),
                "category": category.value,
                "title": issue.title,
                "description": issue.description,
                "recommendation": issue.recommendation,
                "file": issue.file,
                "line": issue.line,
                "source": f"investigator:{category.value}",
            }
            for issue in structured.issues
        ],
        "investigation_depth": "deep",
        "investigation_trace": trace,
    }


def _normalize_severity(raw: str) -> str:
    """Clamp whatever the LLM wrote to a valid Severity value.

    Investigator output goes through `response_format` validation (pydantic
    enforces the field exists and is a string) but not that the *value* is one
    of our four severities -- an LLM could still write "Urgent" or "Info".
    Falling back to "medium" here keeps a single bad value from raising deep
    inside the synthesizer and losing every other category's results.
    """
    normalized = (raw or "").strip().lower()
    return normalized if normalized in _VALID_SEVERITIES else "medium"


def _fallback_result(summary: str) -> Dict[str, Any]:
    return {
        "summary": summary,
        "score": 50.0,  # neutral: we genuinely don't know, not a clean 0 or 100
        "issues": [],
        "investigation_depth": "deep",
        "investigation_trace": [],
    }


def _estimate_run_tokens(prompt: str, messages: List[Any]) -> int:
    """Total token usage for one investigation.

    Each tool-calling turn is its own LLM request that resends the growing
    conversation so far, so summing every message's real `total_tokens` (when
    the provider reports it) correctly reflects cumulative usage against a
    tokens-per-day-style quota -- it's not double-counting, each turn really
    was billed for its own full context. Messages without usage metadata
    (tool outputs, the initial prompt) fall back to the character estimate.
    """
    total = estimate_tokens(prompt)
    for msg in messages:
        tokens = extract_actual_tokens(msg)
        if tokens is None:
            tokens = estimate_tokens(str(getattr(msg, "content", "")))
        total += tokens
    return total


def _extract_trace(messages: List[Any]) -> List[Dict[str, Any]]:
    """Pull (tool, input, observation) triples out of the agent's message history.

    This is what lets the final report show its work: which files/queries an
    investigator actually made, not just its conclusion. `create_agent`
    implements structured final output as a synthetic tool call named after
    the `response_format` class (confirmed live: a tool_call named
    "InvestigationOutput" appears once per run) -- that's the agent
    submitting its answer, not an investigation step, so it's excluded here.
    """
    trace: List[Dict[str, Any]] = []
    pending_calls: Dict[str, Dict[str, Any]] = {}

    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for call in tool_calls:
                if call["name"] == InvestigationOutput.__name__:
                    continue
                pending_calls[call["id"]] = {"tool": call["name"], "tool_input": call["args"]}

        if type(msg).__name__ == "ToolMessage" and msg.tool_call_id in pending_calls:
            call_info = pending_calls[msg.tool_call_id]
            trace.append({**call_info, "observation": str(msg.content)[:500]})

    return trace
