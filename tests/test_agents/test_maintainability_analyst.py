"""Tests for MaintainabilityAnalyst."""

from datetime import datetime, timedelta, timezone

from src.agents.maintainability_analyst import MaintainabilityAnalyst


class TestMaintainabilityAnalyst:
    def test_missing_tests_is_high_severity(self, fake_llm_client):
        agent = MaintainabilityAnalyst(fake_llm_client)
        github_data = {
            "file_structure": {"has_tests": False, "has_ci": True, "has_license": True},
            "stars": 10,
            "pushed_at": datetime.now(timezone.utc).isoformat(),
        }

        result = agent.analyze({"github_metadata": github_data})

        issue = next(i for i in result["issues"] if "test" in i["title"].lower())
        assert issue["severity"] == "high"

    def test_stale_repo_flagged(self, fake_llm_client):
        agent = MaintainabilityAnalyst(fake_llm_client)
        old_date = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
        github_data = {
            "file_structure": {"has_tests": True, "has_ci": True, "has_license": True},
            "stars": 10,
            "pushed_at": old_date,
        }

        result = agent.analyze({"github_metadata": github_data})

        assert any("inactive" in i["title"].lower() for i in result["issues"])

    def test_healthy_repo_has_no_issues(self, fake_llm_client):
        agent = MaintainabilityAnalyst(fake_llm_client)
        github_data = {
            "file_structure": {
                "has_tests": True,
                "has_ci": True,
                "has_license": True,
                "has_contributing": True,
            },
            "stars": 100,
            "pushed_at": datetime.now(timezone.utc).isoformat(),
        }

        result = agent.analyze({"github_metadata": github_data})

        assert result["issues"] == []
        assert result["score"] == 100.0

    def test_missing_contributing_only_flagged_for_popular_repos(self, fake_llm_client):
        agent = MaintainabilityAnalyst(fake_llm_client)
        github_data = {
            "file_structure": {
                "has_tests": True,
                "has_ci": True,
                "has_license": True,
                "has_contributing": False,
            },
            "stars": 5,
            "pushed_at": datetime.now(timezone.utc).isoformat(),
        }

        result = agent.analyze({"github_metadata": github_data})

        assert not any("contributing" in i["title"].lower() for i in result["issues"])
