"""Tests for RepoAnalyzerAgent."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.repo_analyzer import RepoAnalyzerAgent
from src.graph.state import create_initial_state

class TestRepoAnalyzerAgent:
    
    @patch('src.agents.repo_analyzer.GitHubTool')
    @patch('src.agents.repo_analyzer.MarkdownTool')
    def test_initialization(self, mock_markdown, mock_github):
        """Test agent initialization."""
        agent = RepoAnalyzerAgent()
        assert agent.name == "RepoAnalyzer"
    
    @patch('src.agents.repo_analyzer.ChatOpenAI')
    @patch('src.agents.repo_analyzer.GitHubTool')
    @patch('src.agents.repo_analyzer.MarkdownTool')
    def test_execute_success(
        self,
        mock_markdown,
        mock_github,
        mock_llm,
        sample_repo_data,
        sample_readme_analysis
    ):
        """Test successful execution."""
        # Setup mocks
        mock_github_instance = Mock()
        mock_github_instance.execute.return_value = sample_repo_data
        mock_github.return_value = mock_github_instance
        
        mock_markdown_instance = Mock()
        mock_markdown_instance.execute.return_value = sample_readme_analysis
        mock_markdown.return_value = mock_markdown_instance
        
        mock_llm_instance = Mock()
        mock_response = Mock()
        mock_response.content = "Analysis complete"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm.return_value = mock_llm_instance
        
        # Create agent and state
        agent = RepoAnalyzerAgent()
        state = create_initial_state("https://github.com/test/repo")
        
        # Execute
        result = agent.execute(state)
        
        assert "repo_data" in result
        assert result["current_agent"] == "RepoAnalyzer"
