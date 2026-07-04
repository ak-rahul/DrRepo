"""Tests for the repo clone collector. Mocks `subprocess.run` so the unit
suite never needs real network access or a real git clone."""

import subprocess
from unittest.mock import Mock, patch

from src.collectors.repo_clone import clone_repo
from src.models import CollectorStatus


class TestCloneRepo:
    def test_rejects_non_github_url(self, fake_config):
        cloned, result = clone_repo("https://gitlab.com/user/repo", fake_config)

        assert cloned is None
        assert result.status == CollectorStatus.ERROR
        assert "github.com" in result.detail

    @patch("src.collectors.repo_clone.subprocess.run")
    def test_successful_clone_returns_cloned_repo(self, mock_run, fake_config):
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        cloned, result = clone_repo("https://github.com/user/repo", fake_config)

        assert result.status == CollectorStatus.OK
        assert cloned is not None
        assert cloned.repo_url == "https://github.com/user/repo"
        cloned.cleanup()

    @patch("src.collectors.repo_clone.subprocess.run")
    def test_git_clone_failure_returns_error(self, mock_run, fake_config):
        mock_run.return_value = Mock(
            returncode=128, stdout="", stderr="fatal: repository not found"
        )

        cloned, result = clone_repo("https://github.com/user/nonexistent", fake_config)

        assert cloned is None
        assert result.status == CollectorStatus.ERROR
        assert "not found" in result.detail

    @patch("src.collectors.repo_clone.subprocess.run")
    def test_clone_timeout_returns_error(self, mock_run, fake_config):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=60)

        cloned, result = clone_repo("https://github.com/user/repo", fake_config)

        assert cloned is None
        assert result.status == CollectorStatus.ERROR
        assert "timed out" in result.detail

    @patch("src.collectors.repo_clone.subprocess.run")
    def test_missing_git_binary_is_skipped_not_fatal(self, mock_run, fake_config):
        mock_run.side_effect = FileNotFoundError("git not found")

        cloned, result = clone_repo("https://github.com/user/repo", fake_config)

        assert cloned is None
        assert result.status == CollectorStatus.SKIPPED

    @patch("src.collectors.repo_clone._dir_size_mb")
    @patch("src.collectors.repo_clone.subprocess.run")
    def test_oversized_clone_is_skipped_and_cleaned_up(self, mock_run, mock_size, fake_config):
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        mock_size.return_value = 9999.0

        cloned, result = clone_repo("https://github.com/user/repo", fake_config)

        assert cloned is None
        assert result.status == CollectorStatus.SKIPPED
        assert "over the" in result.detail
