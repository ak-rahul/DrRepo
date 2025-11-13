"""Tests for RepoAnalyzer agent."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.repo_analyzer import RepoAnalyzerAgent


class TestRepoAnalyzerAgent:
    """Test cases for RepoAnalyzer agent."""
    
    def test_initialization(self):
        """Test agent initialization."""
        agent = RepoAnalyzerAgent()
        
        assert agent.name == "RepoAnalyzer"
        assert agent.github_tool is not None
        assert agent.markdown_tool is not None
        assert agent.llm is not None
    
    def test_system_prompt_content(self):
        """Test system prompt contains key instructions."""
        agent = RepoAnalyzerAgent()
        
        assert "GitHub repository analysis" in agent.system_prompt
        assert "metadata" in agent.system_prompt.lower()
        assert "README" in agent.system_prompt
    
    @patch('src.agents.repo_analyzer.GitHubTool')
    @patch('src.agents.repo_analyzer.MarkdownTool')
    def test_execute_with_valid_state(
        self, 
        mock_markdown_tool, 
        mock_github_tool, 
        sample_state,
        sample_repo_data,
        mock_llm_response
    ):
        """Test execute method with valid state."""
        # Mock GitHub tool
        mock_github_instance = Mock()
        mock_github_instance.execute.return_value = sample_repo_data
        mock_github_tool.return_value = mock_github_instance
        
        # Mock Markdown tool
        mock_markdown_instance = Mock()
        mock_markdown_instance.execute.return_value = {
            "word_count": 150,
            "section_count": 5,
            "quality_score": 75.0
        }
        mock_markdown_tool.return_value = mock_markdown_instance
        
        # Create agent and mock LLM
        agent = RepoAnalyzerAgent()
        agent._call_llm = Mock(return_value=mock_llm_response)
        
        # Execute
        result = agent.execute(sample_state)
        
        # Assertions
        assert "repo_data" in result
        assert "code_structure" in result
        assert len(result["analysis"]) > 0
        assert result["current_agent"] == "RepoAnalyzer"
        assert result["analysis"][0]["agent"] == "RepoAnalyzer"
    
    def test_create_analysis_prompt(self, sample_repo_data):
        """Test analysis prompt creation."""
        agent = RepoAnalyzerAgent()
        
        readme_analysis = {
            "quality_score": 75.0,
            "word_count": 150,
            "section_count": 5,
            "code_block_count": 2,
            "image_count": 0
        }
        
        prompt = agent._create_analysis_prompt(sample_repo_data, readme_analysis)
        
        # Check prompt contains key information
        assert "test-repo" in prompt
        assert "Python" in prompt
        assert "75" in prompt  # Quality score
        assert "150" in prompt  # Stars
    
    @patch('src.agents.repo_analyzer.GitHubTool')
    def test_execute_handles_errors(self, mock_github_tool, sample_state):
        """Test error handling in execute method."""
        # Mock GitHub tool to raise error
        mock_github_instance = Mock()
        mock_github_instance.execute.side_effect = Exception("API Error")
        mock_github_tool.return_value = mock_github_instance
        
        agent = RepoAnalyzerAgent()
        result = agent.execute(sample_state)
        
        # Should handle error gracefully
        assert len(result["errors"]) > 0
        assert "API Error" in result["errors"][0]
