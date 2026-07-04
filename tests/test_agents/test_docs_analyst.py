"""Tests for DocsAnalyst."""

from src.agents.docs_analyst import DocsAnalyst


class TestDocsAnalyst:
    def test_missing_critical_section_is_high_severity(self, fake_llm_client):
        agent = DocsAnalyst(fake_llm_client)
        readme_data = {
            "word_count": 500,
            "missing_sections": ["Installation"],
            "code_block_count": 1,
            "quality_score": 60.0,
        }

        result = agent.analyze({"readme": readme_data, "github_metadata": {}})

        assert result["issues"][0]["severity"] == "high"
        assert result["score"] == 60.0

    def test_missing_noncritical_section_is_medium_severity(self, fake_llm_client):
        agent = DocsAnalyst(fake_llm_client)
        readme_data = {
            "word_count": 500,
            "missing_sections": ["Examples"],
            "code_block_count": 1,
            "quality_score": 80.0,
        }

        result = agent.analyze({"readme": readme_data, "github_metadata": {}})

        assert result["issues"][0]["severity"] == "medium"

    def test_short_readme_flagged(self, fake_llm_client):
        agent = DocsAnalyst(fake_llm_client)
        readme_data = {
            "word_count": 50,
            "missing_sections": [],
            "code_block_count": 1,
            "quality_score": 20.0,
        }

        result = agent.analyze({"readme": readme_data, "github_metadata": {}})

        assert any("too short" in i["title"].lower() for i in result["issues"])

    def test_complete_readme_has_no_issues(self, fake_llm_client):
        agent = DocsAnalyst(fake_llm_client)
        readme_data = {
            "word_count": 1000,
            "missing_sections": [],
            "code_block_count": 3,
            "quality_score": 95.0,
        }

        result = agent.analyze({"readme": readme_data, "github_metadata": {}})

        assert result["issues"] == []
