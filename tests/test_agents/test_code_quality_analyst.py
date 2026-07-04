"""Tests for CodeQualityAnalyst. Uses a fake LLM client -- no real API key needed."""

from src.agents.code_quality_analyst import CodeQualityAnalyst


class TestCodeQualityAnalyst:
    def test_no_findings_yields_perfect_score_and_no_llm_call(self, fake_llm_client):
        agent = CodeQualityAnalyst(fake_llm_client)

        result = agent.analyze({"static_analysis": {"findings": [], "tool_status": {"ruff": "ok"}}})

        assert result["score"] == 100.0
        assert result["issues"] == []
        fake_llm_client.invoke.assert_not_called()

    def test_findings_produce_issues_with_correct_severity(self, fake_llm_client):
        agent = CodeQualityAnalyst(fake_llm_client)
        findings = [
            {
                "tool": "ruff",
                "file": "app.py",
                "line": 10,
                "rule": "F401",
                "message": "unused import",
            },
            {
                "tool": "semgrep",
                "file": "app.py",
                "line": 20,
                "rule": "sql-injection",
                "message": "possible SQLi",
                "severity": "ERROR",
            },
        ]
        result = agent.analyze({"static_analysis": {"findings": findings, "tool_status": {}}})

        assert len(result["issues"]) == 2
        semgrep_issue = next(i for i in result["issues"] if i["source"] == "semgrep")
        assert semgrep_issue["severity"] == "high"
        assert result["score"] < 100.0
        fake_llm_client.invoke.assert_called_once()

    def test_missing_collector_data_treated_as_no_findings(self, fake_llm_client):
        agent = CodeQualityAnalyst(fake_llm_client)

        result = agent.analyze({})

        assert result["score"] == 100.0
        assert result["issues"] == []
