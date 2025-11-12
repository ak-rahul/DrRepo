"""Tests for GitHubTool."""
import pytest
from unittest.mock import Mock, patch
from src.tools.github_tool import GitHubTool

class TestGitHubTool:
    
    def test_initialization(self, mock_config):
        """Test tool initialization."""
        with patch('src.tools.github_tool.config', mock_config):
            tool = GitHubTool()
            assert tool.name == "GitHubTool"
    
    def test_execute_success(self, mock_github_client, sample_repo_data):
        """Test successful repository fetch."""
        # Mock repository object
        mock_repo = Mock()
        mock_repo.name = sample_repo_data["name"]
        mock_repo.full_name = sample_repo_data["full_name"]
        mock_repo.description = sample_repo_data["description"]
        mock_repo.html_url = sample_repo_data["url"]
        mock_repo.stargazers_count = sample_repo_data["stars"]
        
        # Mock README
        mock_readme = Mock()
        mock_readme.decoded_content.decode.return_value = sample_repo_data["readme_content"]
        mock_repo.get_readme.return_value = mock_readme
        
        # Mock contents
        mock_repo.get_contents.return_value = []
        
        # Setup mock client
        mock_github_client.return_value.get_repo.return_value = mock_repo
        
        tool = GitHubTool()
        result = tool.execute("https://github.com/testuser/test-repo")
        
        assert "name" in result
        assert result["name"] == "test-repo"
    
    def test_execute_invalid_url(self):
        """Test execution with invalid URL."""
        tool = GitHubTool()
        result = tool.execute("invalid-url")
        
        assert "error" in result
