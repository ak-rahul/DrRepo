"""Tests for the Lead Investigator planner. Uses a fake structured-output
client -- no real LLM call needed."""

from unittest.mock import Mock

from src.agents.planner import CategoryPlanOutput, InvestigationPlanOutput, LeadInvestigator
from src.models import InvestigationDepth


def _fake_llm_with_plan(output: InvestigationPlanOutput) -> Mock:
    structured_client = Mock()
    structured_client.invoke = Mock(return_value=output)
    llm_client = Mock()
    llm_client.with_structured_output = Mock(return_value=structured_client)
    return llm_client


class TestLeadInvestigator:
    def test_routes_categories_per_llm_output(self):
        output = InvestigationPlanOutput(
            plans=[
                CategoryPlanOutput(
                    category="security", depth="deep", rationale="bandit found issues"
                ),
                CategoryPlanOutput(
                    category="documentation", depth="shallow", rationale="README looks complete"
                ),
                CategoryPlanOutput(
                    category="code_quality", depth="shallow", rationale="clean ruff pass"
                ),
                CategoryPlanOutput(
                    category="dependencies", depth="deep", rationale="old pinned versions"
                ),
                CategoryPlanOutput(
                    category="maintainability", depth="shallow", rationale="active, has CI"
                ),
            ]
        )
        investigator = LeadInvestigator(_fake_llm_with_plan(output))

        plan = investigator.plan({"stars": 100})

        assert plan.plans["security"].depth == InvestigationDepth.DEEP
        assert plan.plans["documentation"].depth == InvestigationDepth.SHALLOW
        assert plan.plans["dependencies"].depth == InvestigationDepth.DEEP

    def test_missing_category_defaults_to_shallow(self):
        output = InvestigationPlanOutput(
            plans=[
                CategoryPlanOutput(category="security", depth="deep", rationale="x"),
            ]
        )
        investigator = LeadInvestigator(_fake_llm_with_plan(output))

        plan = investigator.plan({})

        assert plan.plans["documentation"].depth == InvestigationDepth.SHALLOW
        assert plan.plans["maintainability"].depth == InvestigationDepth.SHALLOW
        assert len(plan.plans) == 5

    def test_unrecognized_category_is_skipped_not_fatal(self):
        output = InvestigationPlanOutput(
            plans=[
                CategoryPlanOutput(category="bogus_category", depth="deep", rationale="x"),
                CategoryPlanOutput(category="security", depth="deep", rationale="real one"),
            ]
        )
        investigator = LeadInvestigator(_fake_llm_with_plan(output))

        plan = investigator.plan({})

        assert "bogus_category" not in plan.plans
        assert plan.plans["security"].depth == InvestigationDepth.DEEP
        assert len(plan.plans) == 5

    def test_llm_failure_falls_back_to_all_shallow(self):
        structured_client = Mock()
        structured_client.invoke = Mock(side_effect=Exception("API down"))
        llm_client = Mock()
        llm_client.with_structured_output = Mock(return_value=structured_client)

        investigator = LeadInvestigator(llm_client)
        plan = investigator.plan({"stars": 100})

        assert len(plan.plans) == 5
        assert all(p.depth == InvestigationDepth.SHALLOW for p in plan.plans.values())
