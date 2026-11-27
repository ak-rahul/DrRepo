import pytest

from drrepo.models import Category, Severity
from drrepo.report.synthesis import grade, quick_wins, weighted_overall
from tests.report.conftest import _finding, _issue


class TestSynthesizer:
    def test_unassessed_excluded_and_weights_renormalized(self):
        findings = {
            "security": _finding(Category.SECURITY, 40),
            "documentation": _finding(Category.DOCUMENTATION, 80),
            "code_quality": _finding(Category.CODE_QUALITY, 0, assessed=False),
        }
        # (40*0.30 + 80*0.15) / 0.45
        assert weighted_overall(findings) == pytest.approx(53.3, abs=0.1)
        assert weighted_overall({}) == 0.0

    def test_issue_order_and_category_order(self, report_dict):
        assert [i["severity"] for i in report_dict["issues"]] == ["high", "medium", "low"]
        assert list(report_dict["category_scores"]) == ["documentation", "code_quality", "security"]
        assert report_dict["issue_counts"] == {"critical": 0, "high": 1, "medium": 1, "low": 1}

    def test_quick_wins_dedupe(self):
        issues = [_issue(Severity.LOW, f"t{i}", rec="same") for i in range(3)] + [
            _issue(Severity.HIGH, "h", rec="hard")
        ]
        assert quick_wins(issues) == ["same"]

    @pytest.mark.parametrize(
        ("score", "letter"), [(95, "A"), (85, "B"), (70, "C"), (65, "D"), (10, "F")]
    )
    def test_grade(self, score, letter):
        assert grade(score) == letter
