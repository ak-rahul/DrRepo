"""Tests for Web Search tool."""
import pytest
from unittest.mock import Mock, patch
from src.tools.web_search_tool import WebSearchTool


class TestWebSearchTool:
    """Test cases for Web Search tool."""
    
    @patch('src.tools.web_search_tool.TavilyClient')
    def test_initialization(self, mock_tavily):
        """Test tool initialization."""
        tool = WebSearchTool()
        assert tool.client is not None
    
    @patch('src.tools.web_search_tool.TavilyClient')
    def test_search_similar_repositories_success(self, mock_tavily):
        """Test successful similar repository search."""
        # Mock Tavily response
        mock_client = Mock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Awesome Python Repo", "url": "https://github.com/user/repo1"},
                {"title": "Great Testing Tool", "url": "https://github.com/user/repo2"}
            ]
        }
        mock_tavily.return_value = mock_client
        
        tool = WebSearchTool()
        results = tool.search_similar_repositories("Python", "testing framework")
        
        assert len(results) == 2
        assert "Awesome Python Repo" in results[0]["title"]
    
    @patch('src.tools.web_search_tool.TavilyClient')
    def test_search_handles_error(self, mock_tavily):
        """Test error handling in search."""
        mock_client = Mock()
        mock_client.search.side_effect = Exception("API Error")
        mock_tavily.return_value = mock_client
        
        tool = WebSearchTool()
        results = tool.search_similar_repositories("Python", "test")
        
        # Should return empty list on error
        assert results == []
    
    @patch('src.tools.web_search_tool.TavilyClient')
    def test_get_readme_best_practices(self, mock_tavily):
        """Test README best practices search."""
        mock_client = Mock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Best README Practices", "url": "https://example.com/1"},
                {"title": "README Guide", "url": "https://example.com/2"}
            ]
        }
        mock_tavily.return_value = mock_client
        
        tool = WebSearchTool()
        results = tool.get_readme_best_practices()
        
        assert len(results) == 2
        assert "README" in results[0]["title"]
