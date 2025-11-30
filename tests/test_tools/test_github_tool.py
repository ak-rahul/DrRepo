"""Tests for GitHub tool."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from github import GithubException
from src.tools.github_tool import GitHubTool


class TestGitHubTool:
    """Test cases for GitHub tool."""
    
    def test_initialization(self):
        """Test tool initialization."""
        tool = GitHubTool()
        assert tool.github is not None
    
    def test_parse_valid_repo_url(self):
        """Test parsing valid GitHub URLs."""
        tool = GitHubTool()
        
        # Test various valid formats
        assert tool._parse_repo_url("https://github.com/user/repo") == "user/repo"
        assert tool._parse_repo_url("https://github.com/user/repo/") == "user/repo"
        assert tool._parse_repo_url("https://github.com/user-name/repo-name") == "user-name/repo-name"
    
    def test_parse_invalid_repo_url(self):
        """Test parsing invalid URLs."""
        tool = GitHubTool()
        
        # Invalid domain
        with pytest.raises(ValueError):
            tool._parse_repo_url("https://gitlab.com/user/repo")
        
        # Missing repo name
        with pytest.raises(ValueError):
            tool._parse_repo_url("https://github.com/user")
        
        # Completely invalid
        with pytest.raises(ValueError):
            tool._parse_repo_url("not-a-url")
    
    @patch('src.tools.github_tool.Github')
    def test_execute_success(self, mock_github):
        """Test successful repository fetch."""
        # Setup mock
        mock_repo = MagicMock()
        mock_repo.name = "test-repo"
        mock_repo.full_name = "user/test-repo"
        mock_repo.description = "Test description"
        mock_repo.html_url = "https://github.com/user/test-repo"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 20
        mock_repo.watchers_count = 50
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["python", "test"]
        mock_repo.license = Mock(name="MIT")
        mock_repo.size = 1024
        mock_repo.default_branch = "main"
        mock_repo.open_issues_count = 5
        
        # Mock README
        mock_readme = MagicMock()
        mock_readme.decoded_content = b"# Test README"
        mock_repo.get_readme.return_value = mock_readme
        
        # Mock contents
        mock_repo.get_contents.return_value = []
        
        mock_github_instance = Mock()
        mock_github_instance.get_repo.return_value = mock_repo
        mock_github.return_value = mock_github_instance
        
        # Execute
        tool = GitHubTool()
        result = tool.execute("https://github.com/user/test-repo")
        
        # Assertions
        assert result["name"] == "test-repo"
        assert result["full_name"] == "user/test-repo"
        assert result["stars"] == 100
        assert result["language"] == "Python"
        assert "readme_content" in result
        assert "file_structure" in result
    
    @patch('src.tools.github_tool.Github')
    def test_execute_handles_api_error(self, mock_github):
        """Test handling of GitHub API errors."""
        mock_github_instance = Mock()
        mock_github_instance.get_repo.side_effect = GithubException(404, "Not Found", {})
        mock_github.return_value = mock_github_instance
        
        tool = GitHubTool()
        
        with pytest.raises(GithubException):
            tool.execute("https://github.com/user/nonexistent")
    
    @patch('src.tools.github_tool.Github')
    def test_analyze_file_structure(self, mock_github):
        """Test file structure analysis with correct keys."""
        # Setup mock repo with contents that match EXPECTED keys
        mock_repo = MagicMock()
        mock_contents = [
            Mock(name="tests", type="dir"),           # has_tests
            Mock(name=".github/workflows/ci.yml", type="file"),  # has_ci
            Mock(name="docs", type="dir"),            # has_docs  
            Mock(name="LICENSE", type="file"),        # has_license
            Mock(name="CONTRIBUTING.md", type="file"), # has_contributing
            Mock(name="CHANGELOG.md", type="file")    # has_changelog
        ]
        mock_repo.get_contents.return_value = mock_contents
        
        # Mock GitHub instance
        mock_github_instance = Mock()
        mock_github_instance.get_repo.return_value = mock_repo
        mock_github.return_value = mock_github_instance
        
        # Create tool & test
        tool = GitHubTool()
        structure = tool._analyze_file_structure(mock_repo)
        
        # Match YOUR method's ACTUAL keys
        assert isinstance(structure, dict)
        assert structure.get("has_tests") is True
        assert structure.get("has_ci") is True
        assert structure.get("has_docs") is True
        assert structure.get("has_license") is True  # or "has_license_file"
        assert structure.get("has_contributing") is True
        assert structure.get("has_changelog") is True
