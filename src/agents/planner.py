"""Lead Investigator: the planner that decides, per repository, which of the
five categories deserve a deep tool-calling investigation versus a quick
single-call pass over recon data.

This is the piece that makes DrRepo v3 genuinely agentic rather than a fixed
pipeline: the investigation strategy is decided per-repo by the LLM, not
hardcoded.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.models import Category, CategoryPlan, InvestigationDepth, InvestigationPlan
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker, estimate_tokens
from src.utils.logger import logger

_SYSTEM_PROMPT = """You are the lead investigator planning a repository audit. Given initial \
recon signals about a repository, decide which of the five categories deserve a deep, \
tool-calling investigation (reading specific files, searching code, checking dependency \
vulnerabilities in detail) versus a quick pass using only the data already collected.

Categories: documentation, code_quality, security, dependencies, maintainability

Prefer "deep" when:
- Initial signals hint at real risk (e.g. static analysis already found issues, dependencies
  look old or numerous, the repo touches sensitive operations)
- The category's initial data is sparse or ambiguous and deserves a closer look

Prefer "shallow" when initial signals already look clean/complete and a deep dive is unlikely
to change the assessment -- this keeps cost and time down for repos that don't need it.

Always include all five categories in your plan, each with a one-sentence rationale."""


class CategoryPlanOutput(BaseModel):
    category: str = Field(
        description="One of: documentation, code_quality, security, dependencies, maintainability"
    )
    depth: str = Field(description="Either 'shallow' or 'deep'")
    rationale: str = Field(description="One sentence explaining the depth choice")


class InvestigationPlanOutput(BaseModel):
    plans: List[CategoryPlanOutput]


class LeadInvestigator:
    """Plans per-category investigation depth for one analysis run.

    Takes a raw LangChain chat-model client (not the `LLMClient` Protocol used
    by the shallow analysts) because it needs `.with_structured_output()`,
    which is a real LangChain chat-model feature, not something the looser
    Protocol guarantees.
    """

    def __init__(
        self,
        llm_client: Any,
        llm_breaker: Optional[CircuitBreaker] = None,
        llm_budget: Optional[LLMBudgetTracker] = None,
    ):
        self._structured_client = llm_client.with_structured_output(InvestigationPlanOutput)
        self._llm_breaker = llm_breaker
        self._llm_budget = llm_budget

    def plan(self, recon_summary: Dict[str, Any]) -> InvestigationPlan:
        """Produce an `InvestigationPlan` from a recon summary.

        Falls back to an all-shallow plan (equivalent to v2's fixed behavior)
        if the LLM call fails for any reason -- planning failures must never
        block the analysis. A circuit breaker in the OPEN state counts as
        exactly this kind of failure, so a dead LLM quota degrades to the
        same safe shallow-everything behavior rather than raising.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = self._build_prompt(recon_summary)
        messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]

        def _invoke() -> Any:
            return self._structured_client.invoke(messages)

        try:
            result = self._llm_breaker.call(_invoke) if self._llm_breaker else _invoke()
        except Exception as e:
            logger.error(f"LeadInvestigator planning failed, defaulting to all-shallow: {e}")
            return _all_shallow_plan("planner call failed, defaulted to shallow")

        if self._llm_budget is not None:
            # Structured-output calls return a parsed pydantic object, not a
            # raw AIMessage, so there's no usage metadata to extract here --
            # always an estimate.
            self._llm_budget.record(estimate_tokens(_SYSTEM_PROMPT + prompt))

        return _plan_from_output(result)

    @staticmethod
    def _build_prompt(recon_summary: Dict[str, Any]) -> str:
        return (
            f"Recon summary for this repository:\n{recon_summary}\n\n"
            "Produce an investigation plan covering all five categories."
        )


def _plan_from_output(result: InvestigationPlanOutput) -> InvestigationPlan:
    plans: Dict[str, CategoryPlan] = {}
    for item in result.plans:
        try:
            category = Category(item.category)
            depth = InvestigationDepth(item.depth)
        except ValueError:
            logger.warning(f"Planner returned unrecognized category/depth: {item}")
            continue
        plans[category.value] = CategoryPlan(
            category=category, depth=depth, rationale=item.rationale
        )

    # Ensure every category has a plan even if the LLM omitted one.
    for category in Category:
        if category.value not in plans:
            plans[category.value] = CategoryPlan(
                category=category,
                depth=InvestigationDepth.SHALLOW,
                rationale="not specified by planner, defaulted to shallow",
            )

    return InvestigationPlan(plans=plans)


def _all_shallow_plan(rationale: str) -> InvestigationPlan:
    return InvestigationPlan(
        plans={
            c.value: CategoryPlan(category=c, depth=InvestigationDepth.SHALLOW, rationale=rationale)
            for c in Category
        }
    )
