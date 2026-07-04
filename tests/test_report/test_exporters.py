"""Tests for report exporters."""

import json

from src.report.exporters import to_json, to_markdown
from src.report.synthesizer import synthesize_report


def _sample_report():
    category_findings = {
        "security": {
            "summary": "found one issue",
            "score": 70.0,
            "issues": [
                {
                    "severity": "high",
                    "category": "security",
                    "title": "hardcoded secret",
                    "description": "d",
                    "recommendation": "remove it",
                    "file": "app.py",
                    "line": 10,
                }
            ],
        },
    }
    report = synthesize_report(
        {"name": "test-repo", "url": "https://github.com/x/y"}, category_findings, {"ruff": "ok"}
    )
    return report.to_dict()


class TestExporters:
    def test_to_json_is_valid_json_with_expected_shape(self):
        report = _sample_report()
        parsed = json.loads(to_json(report))

        assert parsed["repository"]["name"] == "test-repo"
        assert parsed["issues"][0]["title"] == "hardcoded secret"

    def test_to_markdown_includes_repo_name_and_issue(self):
        report = _sample_report()
        md = to_markdown(report)

        assert "test-repo" in md
        assert "hardcoded secret" in md
        assert "app.py:10" in md
