"""Tests for the report synthesizer."""

from src.report.synthesizer import synthesize_report


class TestSynthesizeReport:
    def test_shallow_category_defaults_when_fields_absent(self):
        """Existing single-call agents don't emit investigation_depth/trace --
        must default cleanly rather than raise."""
        category_findings = {
            "security": {"summary": "s", "score": 100.0, "issues": []},
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        cs = report.category_scores["security"]
        assert cs.investigation_depth.value == "shallow"
        assert cs.investigation_trace == []

    def test_deep_category_carries_investigation_trace(self):
        category_findings = {
            "security": {
                "summary": "investigated",
                "score": 80.0,
                "issues": [],
                "investigation_depth": "deep",
                "investigation_trace": [
                    {
                        "tool": "read_file",
                        "tool_input": {"path": "app.py"},
                        "observation": "import os\n...",
                    }
                ],
            },
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        cs = report.category_scores["security"]
        assert cs.investigation_depth.value == "deep"
        assert len(cs.investigation_trace) == 1
        assert cs.investigation_trace[0].tool == "read_file"

        as_dict = report.to_dict()
        assert as_dict["category_scores"]["security"]["investigation_depth"] == "deep"
        assert (
            as_dict["category_scores"]["security"]["investigation_trace"][0]["tool"] == "read_file"
        )

    def test_perfect_scores_yield_100_overall(self):
        category_findings = {
            "documentation": {"summary": "great docs", "score": 100.0, "issues": []},
            "code_quality": {"summary": "clean", "score": 100.0, "issues": []},
            "security": {"summary": "secure", "score": 100.0, "issues": []},
            "dependencies": {"summary": "up to date", "score": 100.0, "issues": []},
            "maintainability": {"summary": "healthy", "score": 100.0, "issues": []},
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        assert report.overall_score == 100.0
        assert report.issues == []

    def test_issues_sorted_by_severity(self):
        category_findings = {
            "security": {
                "summary": "s",
                "score": 50.0,
                "issues": [
                    {
                        "severity": "low",
                        "category": "security",
                        "title": "low issue",
                        "description": "d",
                        "recommendation": "r",
                    },
                    {
                        "severity": "critical",
                        "category": "security",
                        "title": "critical issue",
                        "description": "d",
                        "recommendation": "r",
                    },
                ],
            },
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        assert report.issues[0].severity.value == "critical"
        assert report.issues[1].severity.value == "low"

    def test_missing_category_excluded_from_weighting(self):
        category_findings = {
            "security": {"summary": "s", "score": 0.0, "issues": []},
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        # Only security contributed, and it scored 0 -- overall should be 0, not
        # artificially averaged against missing categories.
        assert report.overall_score == 0.0

    def test_quick_wins_exclude_critical_and_high(self):
        category_findings = {
            "security": {
                "summary": "s",
                "score": 10.0,
                "issues": [
                    {
                        "severity": "critical",
                        "category": "security",
                        "title": "t",
                        "description": "d",
                        "recommendation": "fix the critical thing",
                    },
                    {
                        "severity": "low",
                        "category": "security",
                        "title": "t2",
                        "description": "d",
                        "recommendation": "fix the low thing",
                    },
                ],
            },
        }

        report = synthesize_report({"name": "test"}, category_findings, {})

        assert "fix the critical thing" not in report.quick_wins
        assert "fix the low thing" in report.quick_wins
