"""Lead Investigator: decides per repository which categories get a deep or
lite tool-calling investigation and which get a quick deterministic pass.

This is what makes the strategy adaptive rather than a fixed pipeline. The
planner is told how many budget units the run can afford (a deep investigation
costs 2, a lite one 1), and `enforce_budget` applies that cap afterwards
regardless of what the model returns.

Naming gotcha (verified live against Groq): pydantic output classes must NOT
start with an underscore -- Groq's tool-calling mangles `_Foo` into ' _Foo' and
rejects the call as "not in request.tools".
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from drrepo.agents import prompts
from drrepo.agents.llm import LLMRuntime
from drrepo.log import logger
from drrepo.models import Category, CategoryPlan, InvestigationDepth, InvestigationPlan

CategoryName = Literal[
    "documentation", "code_quality", "security", "dependencies", "maintainability"
]


class CategoryPlanOutput(BaseModel):
    category: CategoryName
    depth: Literal["shallow", "lite", "deep"]
    rationale: str = Field(description="One sentence citing the recon signal behind the choice")


class InvestigationPlanOutput(BaseModel):
    plans: list[CategoryPlanOutput]


# When the picks cost more than the budget allows, these keep their depth first.
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
        self, recon_summary: dict[str, Any], max_units: int, user_context: str = ""
    ) -> InvestigationPlan:
        """Produce a plan costing at most `max_units` (deep 2, lite 1).

        Never raises: any failure (including an open circuit breaker) yields an
        all-shallow plan, because planning must never block the analysis.
        """
        if max_units <= 0:
            return InvestigationPlan.all_shallow("token budget allows no investigations this run")

        prompt = (
            f"Recon signals:\n{json.dumps(recon_summary, indent=2, default=str)}\n\n"
            + (f"User context: {user_context.strip()}\n\n" if user_context.strip() else "")
            + f"Budget: {max_units} units (deep costs 2, lite costs 1, shallow is free)."
        )
        try:
            result = self._llm.structured(InvestigationPlanOutput, prompts.planner_prompt(), prompt)
        except Exception as e:
            logger.error(f"Lead Investigator planning failed, defaulting to all-shallow: {e}")
            return InvestigationPlan.all_shallow(
                f"planner unavailable ({type(e).__name__}); defaulted to shallow"
            )
        return enforce_budget(plan_from_output(result), max_units)


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


def restrict_plan(plan: InvestigationPlan, allowed: frozenset[str]) -> InvestigationPlan:
    """Make every category outside `allowed` shallow (diff mode: only what got worse)."""
    for name, original in plan.plans.items():
        if name not in allowed and original.depth.investigates:
            plan.plans[name] = CategoryPlan(
                original.category,
                InvestigationDepth.SHALLOW,
                f"{original.rationale} (shallow: unchanged since the base commit)",
            )
    return plan


def enforce_budget(plan: InvestigationPlan, max_units: int) -> InvestigationPlan:
    """Keep the plan within `max_units`, in `DEEP_PRIORITY` order.

    A deep pick that no longer fits becomes lite if one unit is left, else
    shallow; a lite pick that doesn't fit becomes shallow.
    """
    remaining = max(0, max_units)
    for category in DEEP_PRIORITY:
        original = plan.plans[category.value]
        depth = original.depth
        if not depth.investigates:
            continue
        if depth.budget_units > remaining:
            depth = InvestigationDepth.LITE if remaining >= 1 else InvestigationDepth.SHALLOW
            plan.plans[category.value] = CategoryPlan(
                category,
                depth,
                f"{original.rationale} (downgraded to {depth.value}: the run token budget "
                f"allows {max_units} unit(s))",
            )
        remaining -= depth.budget_units
    return plan
