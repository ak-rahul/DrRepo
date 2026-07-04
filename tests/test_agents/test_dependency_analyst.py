"""Tests for DependencyAnalyst."""

from src.agents.dependency_analyst import DependencyAnalyst


class TestDependencyAnalyst:
    def test_no_manifests_found(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)

        result = agent.analyze({"dependency_audit": {"packages_checked": 0, "vulnerabilities": []}})

        assert result["score"] == 100.0
        assert result["issues"] == []
        fake_llm_client.invoke.assert_not_called()

    def test_no_vulnerabilities_found_still_scores_perfect(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)

        result = agent.analyze(
            {"dependency_audit": {"packages_checked": 10, "vulnerabilities": []}}
        )

        assert result["score"] == 100.0
        fake_llm_client.invoke.assert_not_called()

    def test_vulnerability_produces_issue_with_osv_link(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        vulns = [
            {
                "package": "requests",
                "version": "2.6.0",
                "ecosystem": "PyPI",
                "vuln_id": "PYSEC-2018-28",
            }
        ]

        result = agent.analyze(
            {"dependency_audit": {"packages_checked": 1, "vulnerabilities": vulns}}
        )

        assert len(result["issues"]) == 1
        assert "osv.dev/vulnerability/PYSEC-2018-28" in result["issues"][0]["recommendation"]
        assert result["score"] < 100.0
        fake_llm_client.invoke.assert_called_once()
