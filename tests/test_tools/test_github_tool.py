"""Tests for GitHub Tool."""

import pytest
from unittest.mock import Mock, patch
from github import GithubException

from src.tools.github_tool import GitHubTool
from src.utils.exceptions import ValidationError, RepositoryNotFoundError


class TestGitHubTool:
    """Test cases for GitHubTool."""

    @patch('src.tools.github_tool.Github')
    def test_initialization(self, mock_github):
        """Test GitHubTool initialization."""
        tool = GitHubTool()
        assert tool is not None

    def test_parse_valid_repo_url(self):
        """Test parsing valid GitHub URLs."""
        tool = GitHubTool()
        
        result = tool._parse_repo_url("https://github.com/user/repo")
        assert result == "user/repo"
        
        result = tool._parse_repo_url("https://github.com/user/repo/")
        assert result == "user/repo"

    def test_parse_invalid_repo_url(self):
        """Test parsing invalid URLs."""
        tool = GitHubTool()

        # Invalid domain
        with pytest.raises(ValidationError):
            tool._parse_repo_url("https://gitlab.com/user/repo")

        # Empty URL
        with pytest.raises(ValidationError):
            tool._parse_repo_url("")

        # Missing repo name
        with pytest.raises(ValidationError):
            tool._parse_repo_url("https://github.com/user")

    @patch('src.tools.github_tool.Github')
    def test_execute_success(self, mock_github):
        """Test successful repository fetch."""
        # Mock repository object
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
        mock_repo.license = None
        mock_repo.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
        mock_repo.pushed_at.isoformat.return_value = "2024-01-03T00:00:00"
        mock_repo.size = 1000
        mock_repo.default_branch = "main"
        mock_repo.open_issues_count = 5

        # Mock README
        mock_readme = Mock()
        mock_readme.decoded_content.decode.return_value = "# Test Repo\nThis is a test."
        mock_repo.get_readme.return_value = mock_readme

        # Mock file structure
        mock_repo.get_contents.return_value = []

        mock_github_instance = Mock()
        mock_github_instance.get_repo.return_value = mock_repo
        mock_github.return_value = mock_github_instance

        tool = GitHubTool()
        result = tool.execute("https://github.com/user/test-repo")

        assert result["name"] == "test-repo"
        assert result["stars"] == 100

    @patch('src.tools.github_tool.Github')
    def test_execute_handles_api_error(self, mock_github):
        """Test handling of GitHub API errors."""
        mock_github_instance = Mock()
        mock_github_instance.get_repo.side_effect = GithubException(404, "Not Found", {})
        mock_github.return_value = mock_github_instance

        tool = GitHubTool()

        with pytest.raises(RepositoryNotFoundError):
            tool.execute("https://github.com/user/nonexistent")

    @patch('src.tools.github_tool.Github')
    def test_analyze_file_structure(self, mock_github):
        """Test file structure analysis with mocked repository contents."""
        # Create mock content objects
        mock_contents = []
        
        # Add various file types
        test_files = [
            "tests",           # Test directory
            ".github",         # CI/CD
            "docs",            # Documentation
            "LICENSE",         # License file
            "CONTRIBUTING.md", # Contributing guide
            "CHANGELOG.md",    # Changelog
            "README.md",       # Regular file
            "src"              # Source directory
        ]
        
        for filename in test_files:
            mock_content = Mock()
            mock_content.name = filename
            mock_contents.append(mock_content)
        
        # Mock repository
        mock_repo = Mock()
        mock_repo.get_contents.return_value = mock_contents
        
        mock_github_instance = Mock()
        mock_github.return_value = mock_github_instance
        
        # Create tool and test
        tool = GitHubTool()
        structure = tool._analyze_file_structure(mock_repo)
        
        # Verify all flags are set correctly
        assert structure["has_tests"] is True
        assert structure["has_ci"] is True
        assert structure["has_docs"] is True
        assert structure["has_license"] is True
        assert structure["has_contributing"] is True
        assert structure["has_changelog"] is True

    @patch('src.tools.github_tool.Github')
    def test_analyze_file_structure_minimal(self, mock_github):
        """Test file structure analysis with minimal repository."""
        # Create mock with only README
        mock_content = Mock()
        mock_content.name = "README.md"
        
        # Mock repository
        mock_repo = Mock()
        mock_repo.get_contents.return_value = [mock_content]
        
        mock_github_instance = Mock()
        mock_github.return_value = mock_github_instance
        
        # Create tool and test
        tool = GitHubTool()
        structure = tool._analyze_file_structure(mock_repo)
        
        # Verify all flags are False for minimal repo
        assert structure["has_tests"] is False
        assert structure["has_ci"] is False
        assert structure["has_docs"] is False
        assert structure["has_license"] is False
        assert structure["has_contributing"] is False
        assert structure["has_changelog"] is False

    @patch('src.tools.github_tool.Github')
    def test_analyze_file_structure_handles_error(self, mock_github):
        """Test file structure analysis handles errors gracefully."""
        # Mock repository that raises exception
        mock_repo = Mock()
        mock_repo.get_contents.side_effect = GithubException(403, "Rate limit", {})
        
        mock_github_instance = Mock()
        mock_github.return_value = mock_github_instance
        
        # Create tool and test
        tool = GitHubTool()
        structure = tool._analyze_file_structure(mock_repo)
        
        # Should return partial structure without raising exception
        assert isinstance(structure, dict)
        assert "has_tests" in structure
        assert "has_ci" in structure
