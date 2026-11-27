"""Bounded tool-calling investigator (ReAct loop) for one category.

Built on `langchain.agents.create_agent` (the current API;
`langgraph.prebuilt.create_react_agent` is deprecated since LangGraph 1.0).
The LLM chooses which tools to call, with what arguments, and when it has
enough evidence, then submits structured findings via `response_format`.

Bounds on every investigation:
- steps: `recursion_limit = max_tool_calls * 2 + 4` (each tool round-trip is
  ~2 graph steps); exhaustion raises `GraphRecursionError`;
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
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from drrepo.agents.llm import LLMRuntime
from drrepo.core.budget import estimate_tokens, extract_actual_tokens
from drrepo.core.errors import CircuitOpenError, DrRepoError
from drrepo.core.log import logger
from drrepo.models import Category, Issue, Location, Severity, ToolCallTrace

MAX_LIST_ITEMS_IN_PROMPT = 15
MAX_TEXT_FIELD_CHARS = 1500
MAX_OBSERVATION_CHARS = 600


class InvestigationError(DrRepoError):
    """The deep investigation could not produce a result; `reason` is user-presentable."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# Public names on purpose -- see the naming gotcha in planner.py.
class IssueOutput(BaseModel):
    severity: str = Field(description="One of: critical, high, medium, low")
    title: str = Field(description="Short, specific title")
    description: str = Field(description="What is wrong and the evidence you found for it")
    recommendation: str = Field(description="Concrete fix")
    file: str | None = Field(default=None, description="Repo-relative path where the evidence is")
    line: int | None = None


class InvestigationOutput(BaseModel):
    summary: str = Field(description="3-5 sentence narrative of what you checked and found")
    issues: list[IssueOutput] = Field(default_factory=list)


@dataclass
class InvestigationResult:
    summary: str
    issues: list[Issue]
    trace: list[ToolCallTrace] = field(default_factory=list)


def _summarize_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT_FIELD_CHARS:
        return value[:MAX_TEXT_FIELD_CHARS] + f"... [truncated, {len(value)} chars total]"
    if isinstance(value, list):
        kept = [_summarize_value(v) for v in value[:MAX_LIST_ITEMS_IN_PROMPT]]
        if len(value) > MAX_LIST_ITEMS_IN_PROMPT:
            kept.append(f"... and {len(value) - MAX_LIST_ITEMS_IN_PROMPT} more")
        return kept
    if isinstance(value, dict):
        return {k: _summarize_value(v) for k, v in value.items()}
    return value


def summarize_recon_data(recon_data: dict[str, Any]) -> dict[str, Any]:
    """Bound every long string and list (recursively) before it enters a prompt.
    The investigator can still `read_file`/`search_code` for anything trimmed."""
    return {name: _summarize_value(data) for name, data in recon_data.items()}


def build_prompt(
    recon_data: dict[str, Any], known_issues: list[Issue], user_context: str = ""
) -> str:
    known = (
        "\n".join(
            f"- [{i.severity.value}] {i.title} ({i.file or 'n/a'})" for i in known_issues[:25]
        )
        or "- none"
    )
    return (
        "Recon data already collected for this repository (trimmed):\n"
        f"{json.dumps(summarize_recon_data(recon_data), indent=1, default=str)}\n\n"
        f"Issues already reported by automated tools (do not repeat these):\n{known}\n\n"
        + (f"User context: {user_context.strip()}\n\n" if user_context.strip() else "")
        + "Investigate using the tools available. Only call tools that are useful, and stop once "
        "you have enough evidence. Report only NEW issues you verified with a tool; cite the file. "
        "If you find nothing new, return an empty issue list -- that is a valid outcome."
    )


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
) -> InvestigationResult:
    """Run one bounded investigation. Raises `InvestigationError` on any failure."""
    from langchain.agents import create_agent

    agent = create_agent(
        model=llm.client,
        tools=tools,
        system_prompt=system_prompt,
        response_format=InvestigationOutput,
    )
    prompt = build_prompt(recon_data, known_issues, user_context)
    recursion_limit = max_tool_calls * 2 + 4

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
        raise InvestigationError(f"failed: {type(e).__name__}: {str(e)[:200]}") from e

    messages = result.get("messages", [])
    if llm.budget is not None:
        llm.budget.record(estimate_run_tokens(prompt, messages))

    structured = result.get("structured_response")
    if not isinstance(structured, InvestigationOutput):
        raise InvestigationError("finished without submitting structured findings")

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
        for item in structured.issues
        if item.title.strip()
    ]
    return InvestigationResult(
        summary=structured.summary.strip(), issues=issues, trace=extract_trace(messages)
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
            trace.append(
                ToolCallTrace(
                    tool=tool,
                    tool_input=tool_input,
                    observation=str(msg.content)[:MAX_OBSERVATION_CHARS],
                )
            )
    return trace
