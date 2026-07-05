"""Tests for shared model helpers."""

from src.models import Category, CategoryPlan, InvestigationDepth, InvestigationPlan


class TestInvestigationPlan:
    def test_depth_for_known_category(self):
        plan = InvestigationPlan(
            plans={
                "security": CategoryPlan(
                    category=Category.SECURITY,
                    depth=InvestigationDepth.DEEP,
                    rationale="high stars, security-sensitive",
                )
            }
        )

        assert plan.depth_for(Category.SECURITY) == InvestigationDepth.DEEP

    def test_depth_for_missing_category_defaults_shallow(self):
        plan = InvestigationPlan(plans={})

        assert plan.depth_for(Category.DOCUMENTATION) == InvestigationDepth.SHALLOW
