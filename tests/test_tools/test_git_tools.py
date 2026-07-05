"""Tests for the file commit-history tool (queries GitHub's API, not local git log,
since shallow clones only ever have one commit -- see git_tools.py's module docstring)."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.tools.git_tools import make_git_history_tools


class TestGetFileGitHistory:
    @patch("src.tools.git_tools.Github")
    def test_returns_formatted_commit_history(self, mock_github_cls, fake_config):
        mock_commit = Mock()
        mock_commit.sha = "abc1234567890"
        mock_commit.commit.author.name = "Jane Dev"
        mock_commit.commit.author.date = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_commit.commit.message = "Fix bug in parser\n\nLonger body text"

        mock_repo = Mock()
        mock_repo.get_commits.return_value = [mock_commit]
        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_gh_instance

        (get_history,) = make_git_history_tools("user/repo", fake_config)
        result = get_history.invoke({"path": "src/parser.py"})

        assert "abc1234" in result
        assert "2025-01-15" in result
        assert "Jane Dev" in result
        assert "Fix bug in parser" in result

    @patch("src.tools.git_tools.Github")
    def test_no_history_found(self, mock_github_cls, fake_config):
        mock_repo = Mock()
        mock_repo.get_commits.return_value = []
        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_gh_instance

        (get_history,) = make_git_history_tools("user/repo", fake_config)
        result = get_history.invoke({"path": "src/nonexistent.py"})

        assert "No commit history found" in result

    @patch("src.tools.git_tools.Github")
    def test_github_error_returns_error_string(self, mock_github_cls, fake_config):
        from github import GithubException

        mock_gh_instance = Mock()
        mock_gh_instance.get_repo.side_effect = GithubException(404, "Not Found", {})
        mock_github_cls.return_value = mock_gh_instance

        (get_history,) = make_git_history_tools("user/repo", fake_config)
        result = get_history.invoke({"path": "src/main.py"})

        assert result.startswith("ERROR")
