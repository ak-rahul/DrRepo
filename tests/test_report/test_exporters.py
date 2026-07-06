"""Tests for report exporters."""

import json

from src.report.exporters import to_json, to_markdown, to_sarif
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
                    "source": "bandit",
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

    def test_to_markdown_escapes_pipe_in_summary(self):
        report = _sample_report()
        report["category_scores"]["security"]["summary"] = "found a | in the summary"

        md = to_markdown(report)

        table_row = next(line for line in md.splitlines() if line.startswith("| Security"))
        assert table_row == "| Security | 70.0/100 | found a \\| in the summary |"

    def test_to_sarif_is_valid_json_with_expected_shape(self):
        report = _sample_report()
        sarif = json.loads(to_sarif(report))

        assert sarif["version"] == "2.1.0"
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "DrRepo"
        result = run["results"][0]
        assert result["ruleId"] == "bandit"
        assert result["level"] == "error"
        assert "hardcoded secret" in result["message"]["text"]
        assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "app.py"
        assert result["locations"][0]["physicalLocation"]["region"]["startLine"] == 10

    def test_to_sarif_declares_one_rule_per_distinct_source(self):
        report = _sample_report()
        sarif = json.loads(to_sarif(report))

        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        assert [r["id"] for r in rules] == ["bandit"]

    def test_to_sarif_omits_locations_when_issue_has_no_file(self):
        category_findings = {
            "dependencies": {
                "summary": "s",
                "score": 60.0,
                "issues": [
                    {
                        "severity": "medium",
                        "category": "dependencies",
                        "title": "some-gpl-lib: GPL-3.0 dependency",
                        "description": "d",
                        "recommendation": "review it",
                        "file": None,
                        "line": None,
                        "source": "license-audit",
                    }
                ],
            },
        }
        report = synthesize_report(
            {"name": "test-repo", "url": "https://github.com/x/y"}, category_findings, {}
        ).to_dict()

        sarif = json.loads(to_sarif(report))
        result = sarif["runs"][0]["results"][0]

        assert result["level"] == "warning"
        assert "locations" not in result

    def test_to_sarif_with_no_issues_has_empty_results(self):
        report = synthesize_report(
            {"name": "test-repo", "url": "https://github.com/x/y"}, {}, {}
        ).to_dict()

        sarif = json.loads(to_sarif(report))

        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["rules"] == []
