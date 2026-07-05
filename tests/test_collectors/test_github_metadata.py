"""Tests for the GitHub metadata collector."""

from unittest.mock import Mock, patch

from github import GithubException

from src.collectors.github_metadata import collect_github_metadata, parse_repo_path
from src.models import CollectorStatus


class TestParseRepoPath:
    def test_valid_url(self):
        assert parse_repo_path("https://github.com/user/repo") == "user/repo"
        assert parse_repo_path("https://github.com/user/repo/") == "user/repo"

    def test_invalid_domain_raises(self):
        import pytest

        with pytest.raises(ValueError):
            parse_repo_path("https://gitlab.com/user/repo")

    def test_empty_url_raises(self):
        import pytest

        with pytest.raises(ValueError):
            parse_repo_path("")

    def test_missing_repo_name_raises(self):
        import pytest

        with pytest.raises(ValueError):
            parse_repo_path("https://github.com/user")


class TestCollectGithubMetadata:
    @patch("src.collectors.github_metadata.Github")
    def test_successful_fetch(self, mock_github_cls, fake_config):
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.full_name = "user/test-repo"
        mock_repo.description = "A test repository"
        mock_repo.html_url = "https://github.com/user/test-repo"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 50
        mock_repo.watchers_count = 75
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["python", "testing"]
        mock_license = Mock()
        mock_license.name = "MIT License"
        mock_license.spdx_id = "MIT"
        mock_repo.license = mock_license
        mock_repo.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
        mock_repo.pushed_at.isoformat.return_value = "2024-01-03T00:00:00"
        mock_repo.size = 1000
        mock_repo.default_branch = "main"
        mock_repo.open_issues_count = 5

        mock_readme = Mock()
        mock_readme.decoded_content.decode.return_value = "# Test Repo\nThis is a test."
        mock_repo.get_readme.return_value = mock_readme
        mock_repo.get_contents.return_value = []

        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_gh_instance

        result = collect_github_metadata("https://github.com/user/test-repo", fake_config)

        assert result.status == CollectorStatus.OK
        assert result.data["name"] == "test-repo"
        assert result.data["stars"] == 100
        assert result.data["license"] == "MIT License"
        assert result.data["license_spdx_id"] == "MIT"

    @patch("src.collectors.github_metadata.Github")
    def test_no_license_gives_none_for_both_fields(self, mock_github_cls, fake_config):
        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.full_name = "user/test-repo"
        mock_repo.description = ""
        mock_repo.html_url = "https://github.com/user/test-repo"
        mock_repo.stargazers_count = 0
        mock_repo.forks_count = 0
        mock_repo.watchers_count = 0
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = []
        mock_repo.license = None
        mock_repo.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.updated_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.pushed_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.size = 10
        mock_repo.default_branch = "main"
        mock_repo.open_issues_count = 0
        mock_repo.get_readme.side_effect = GithubException(404, "Not Found", {})
        mock_repo.get_contents.return_value = []

        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_gh_instance

        result = collect_github_metadata("https://github.com/user/test-repo", fake_config)

        assert result.data["license"] is None
        assert result.data["license_spdx_id"] is None

    @patch("src.collectors.github_metadata.Github")
    def test_repository_not_found(self, mock_github_cls, fake_config):
        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.side_effect = GithubException(404, "Not Found", {})
        mock_github_cls.return_value = mock_gh_instance

        result = collect_github_metadata("https://github.com/user/nonexistent", fake_config)

        assert result.status == CollectorStatus.ERROR
        assert "not found" in result.detail.lower()

    def test_invalid_url_returns_error_without_network_call(self, fake_config):
        result = collect_github_metadata("https://gitlab.com/user/repo", fake_config)

        assert result.status == CollectorStatus.ERROR

    @patch("src.collectors.github_metadata.Github")
    def test_file_structure_detection(self, mock_github_cls, fake_config):
        mock_contents = []
        for filename in ["tests", ".github", "docs", "LICENSE", "CONTRIBUTING.md", "CHANGELOG.md"]:
            content = Mock()
            content.name = filename
            mock_contents.append(content)

        mock_repo = Mock()
        mock_repo.name = "test-repo"
        mock_repo.full_name = "user/test-repo"
        mock_repo.description = ""
        mock_repo.html_url = "https://github.com/user/test-repo"
        mock_repo.stargazers_count = 0
        mock_repo.forks_count = 0
        mock_repo.watchers_count = 0
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = []
        mock_repo.license = None
        mock_repo.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.updated_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.pushed_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.size = 10
        mock_repo.default_branch = "main"
        mock_repo.open_issues_count = 0
        mock_repo.get_readme.side_effect = GithubException(404, "Not Found", {})
        mock_repo.get_contents.return_value = mock_contents

        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_gh_instance

        result = collect_github_metadata("https://github.com/user/test-repo", fake_config)

        structure = result.data["file_structure"]
        assert structure["has_tests"] is True
        assert structure["has_ci"] is True
        assert structure["has_docs"] is True
        assert structure["has_license"] is True
        assert structure["has_contributing"] is True
        assert structure["has_changelog"] is True
        assert result.data["readme_content"] == ""
