"""Tests for SecurityAnalyst."""

from src.agents.security_analyst import SecurityAnalyst


class TestSecurityAnalyst:
    def test_no_findings_yields_perfect_score(self, fake_llm_client):
        agent = SecurityAnalyst(fake_llm_client)

        result = agent.analyze({"security": {"findings": [], "tool_status": {"bandit": "ok"}}})

        assert result["score"] == 100.0
        assert result["issues"] == []

    def test_secret_scan_finding_is_critical_severity(self, fake_llm_client):
        agent = SecurityAnalyst(fake_llm_client)
        findings = [
            {
                "tool": "secret_scan",
                "file": "config.py",
                "line": 3,
                "rule": "AWS Access Key",
                "message": "Possible AWS Access Key committed to source",
            }
        ]
        result = agent.analyze({"security": {"findings": findings, "tool_status": {}}})

        assert result["issues"][0]["severity"] == "critical"
        assert "rotate" in result["issues"][0]["recommendation"].lower()

    def test_bandit_severity_mapping(self, fake_llm_client):
        agent = SecurityAnalyst(fake_llm_client)
        findings = [
            {"tool": "bandit", "rule": "B105", "message": "hardcoded password", "severity": "LOW"},
        ]
        result = agent.analyze({"security": {"findings": findings, "tool_status": {}}})

        assert result["issues"][0]["severity"] == "low"

    def test_score_penalizes_more_for_critical_than_low(self, fake_llm_client):
        agent = SecurityAnalyst(fake_llm_client)
        low_result = agent.analyze(
            {
                "security": {
                    "findings": [
                        {"tool": "bandit", "rule": "x", "message": "m", "severity": "LOW"}
                    ],
                    "tool_status": {},
                }
            }
        )
        critical_result = agent.analyze(
            {
                "security": {
                    "findings": [{"tool": "secret_scan", "rule": "x", "message": "m"}],
                    "tool_status": {},
                }
            }
        )
        assert critical_result["score"] < low_result["score"]
