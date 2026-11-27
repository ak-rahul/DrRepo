"""Lead Investigator: decides per repository which categories get a deep,
tool-calling investigation and which get a quick deterministic pass.

This is what makes the strategy adaptive rather than a fixed pipeline. The
planner is told how many deep investigations the run can afford, and the
workflow enforces that cap afterwards regardless of what the model returns.

Naming gotcha (verified live against Groq): pydantic output classes must NOT
start with an underscore -- Groq's tool-calling mangles `_Foo` into ' _Foo' and
rejects the call as "not in request.tools".
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from drrepo.agents.llm import LLMRuntime
from drrepo.log import logger
from drrepo.models import Category, CategoryPlan, InvestigationDepth, InvestigationPlan

SYSTEM_PROMPT = """You are the lead investigator planning a repository audit. From initial recon \
signals, decide for each of five categories whether it deserves a DEEP tool-calling \
investigation (reading files, searching code, re-running scanners, querying advisories) or a \
SHALLOW pass that only summarizes the automated results.

Prefer "deep" when signals suggest real risk or ambiguity: many or severe scanner findings, \
possible secrets, vulnerable or unpinned dependencies, a category whose automated data is thin \
or was unavailable, or something the user specifically asked about.
Prefer "shallow" when automated signals are clean and complete, so time and tokens go where \
they matter. You may choose at most the stated number of deep categories; rank by risk.

Return all five categories, each with a one-sentence rationale grounded in the recon signals."""

CategoryName = Literal[
    "documentation", "code_quality", "security", "dependencies", "maintainability"
]


class CategoryPlanOutput(BaseModel):
    category: CategoryName
    depth: Literal["shallow", "deep"]
    rationale: str = Field(description="One sentence citing the recon signal behind the choice")


class InvestigationPlanOutput(BaseModel):
    plans: list[CategoryPlanOutput]


# When more categories are flagged deep than the budget allows, keep these first.
DEEP_PRIORITY = [
    Category.SECURITY,
    Category.DEPENDENCIES,
    Category.CODE_QUALITY,
    Category.MAINTAINABILITY,
    Category.DOCUMENTATION,
]


class LeadInvestigator:
    def __init__(self, llm: LLMRuntime):
        self._llm = llm

    def plan(
        self, recon_summary: dict[str, Any], max_deep: int, user_context: str = ""
    ) -> InvestigationPlan:
        """Produce a plan with at most `max_deep` deep categories.

        Never raises: any failure (including an open circuit breaker) yields an
        all-shallow plan, because planning must never block the analysis.
        """
        if max_deep <= 0:
            return InvestigationPlan.all_shallow(
                "token budget allows no deep investigations this run"
            )

        prompt = (
            f"Recon signals:\n{json.dumps(recon_summary, indent=2, default=str)}\n\n"
            + (f"User context: {user_context.strip()}\n\n" if user_context.strip() else "")
            + f"You may mark at most {max_deep} categories as deep."
        )
        try:
            result = self._llm.structured(InvestigationPlanOutput, SYSTEM_PROMPT, prompt)
        except Exception as e:
            logger.error(f"Lead Investigator planning failed, defaulting to all-shallow: {e}")
            return InvestigationPlan.all_shallow(
                f"planner unavailable ({type(e).__name__}); defaulted to shallow"
            )
        return enforce_deep_cap(plan_from_output(result), max_deep)


def plan_from_output(result: InvestigationPlanOutput) -> InvestigationPlan:
    plans: dict[str, CategoryPlan] = {}
    for item in result.plans:
        try:
            category = Category(item.category)
            depth = InvestigationDepth(item.depth)
        except ValueError:
            logger.warning(f"Planner returned unrecognized category/depth: {item}")
            continue
        plans.setdefault(category.value, CategoryPlan(category, depth, item.rationale))

    for category in Category:
        plans.setdefault(
            category.value,
            CategoryPlan(
                category,
                InvestigationDepth.SHALLOW,
                "not specified by planner; defaulted to shallow",
            ),
        )
    return InvestigationPlan(plans=plans)


def enforce_deep_cap(plan: InvestigationPlan, max_deep: int) -> InvestigationPlan:
    """Downgrade the lowest-priority deep categories beyond `max_deep`."""
    deep = [c for c in DEEP_PRIORITY if plan.depth_for(c) == InvestigationDepth.DEEP]
    for category in deep[max(0, max_deep) :]:
        original = plan.plans[category.value]
        plan.plans[category.value] = CategoryPlan(
            category,
            InvestigationDepth.SHALLOW,
            f"{original.rationale} (downgraded to shallow: run token budget allows {max_deep} deep investigation(s))",
        )
    return plan
