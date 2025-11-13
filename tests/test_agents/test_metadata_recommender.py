"""Tests for MetadataRecommender agent."""
import pytest
from unittest.mock import Mock, patch
from src.agents.metadata_recommender import MetadataRecommenderAgent


class TestMetadataRecommenderAgent:
    """Test cases for MetadataRecommender agent."""
    
    def test_initialization(self):
        """Test agent initialization."""
        agent = MetadataRecommenderAgent()
        
        assert agent.name == "MetadataRecommender"
        assert agent.web_search is not None
        assert agent.llm is not None
    
    def test_system_prompt_content(self):
        """Test system prompt contains key instructions."""
        agent = MetadataRecommenderAgent()
        
        assert "metadata" in agent.system_prompt.lower()
        assert "topics" in agent.system_prompt.lower()
        assert "discoverability" in agent.system_prompt.lower()
    
    @patch('src.agents.metadata_recommender.WebSearchTool')
    def test_execute_with_valid_state(
        self,
        mock_web_search,
        sample_state,
        sample_repo_data,
        mock_llm_response
    ):
        """Test execute method with valid state."""
        # Setup state with repo data
        sample_state["repo_data"] = sample_repo_data
        
        # Mock web search
        mock_search_instance = Mock()
        mock_search_instance.search_similar_repositories.return_value = [
            {"title": "Similar Repo 1", "topics": ["python", "testing"]},
            {"title": "Similar Repo 2", "topics": ["automation", "python"]}
        ]
        mock_web_search.return_value = mock_search_instance
        
        # Create agent and mock LLM
        agent = MetadataRecommenderAgent()
        agent._call_llm = Mock(return_value=mock_llm_response)
        
        # Execute
        result = agent.execute(sample_state)
        
        # Assertions
        assert len(result["metadata_recommendations"]) > 0
        assert result["current_agent"] == "MetadataRecommender"
        assert "recommendations" in result["metadata_recommendations"][0]
    
    def test_create_recommendation_prompt(self, sample_repo_data):
        """Test recommendation prompt creation."""
        agent = MetadataRecommenderAgent()
        
        similar_repos = [
            {"title": "Awesome Project", "topics": ["python", "awesome"]},
            {"title": "Cool Tool", "topics": ["tool", "python"]}
        ]
        
        prompt = agent._create_recommendation_prompt(sample_repo_data, similar_repos)
        
        # Check prompt contains key information
        assert "test-repo" in prompt
        assert "Python" in prompt
        assert "Awesome Project" in prompt
        assert "Topics" in prompt
    
    @patch('src.agents.metadata_recommender.WebSearchTool')
    def test_execute_handles_errors(self, mock_web_search, sample_state, sample_repo_data):
        """Test error handling in execute method."""
        sample_state["repo_data"] = sample_repo_data
        
        # Mock web search to raise error
        mock_search_instance = Mock()
        mock_search_instance.search_similar_repositories.side_effect = Exception("Search Error")
        mock_web_search.return_value = mock_search_instance
        
        agent = MetadataRecommenderAgent()
        result = agent.execute(sample_state)
        
        # Should handle error gracefully
        assert len(result["errors"]) > 0
