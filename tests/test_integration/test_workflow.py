"""Integration tests for complete workflow."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.graph.workflow import PublicationAssistantWorkflow
from src.main import PublicationAssistant


@pytest.mark.integration
class TestWorkflowIntegration:
    """Integration tests for workflow."""
    
    @patch('src.tools.github_tool.Github')
    @patch('src.tools.web_search_tool.TavilyClient')
    def test_complete_workflow_execution(
        self,
        mock_tavily,
        mock_github,
        sample_repo_data,
        mock_llm_response
    ):
        """Test complete workflow execution."""
        # Mock GitHub
        mock_repo = MagicMock()
        mock_repo.name = "test-repo"
        mock_repo.full_name = "user/test-repo"
        mock_repo.description = "Test"
        mock_repo.html_url = "https://github.com/user/test-repo"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 20
        mock_repo.watchers_count = 50
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["python"]
        mock_repo.license = Mock(name="MIT")
        
        mock_readme = MagicMock()
        mock_readme.decoded_content = b"# Test\n\n## Installation\n\n``````"
        mock_repo.get_readme.return_value = mock_readme
        mock_repo.get_contents.return_value = []
        
        mock_github_instance = Mock()
        mock_github_instance.get_repo.return_value = mock_repo
        mock_github.return_value = mock_github_instance
        
        # Mock Tavily
        mock_tavily_instance = Mock()
        mock_tavily_instance.search.return_value = {"results": []}
        mock_tavily.return_value = mock_tavily_instance
        
        # Create workflow
        workflow = PublicationAssistantWorkflow()
        
        # Mock all LLM calls
        for agent in [workflow.repo_analyzer, workflow.metadata_recommender,
                     workflow.content_improver, workflow.reviewer_critic,
                     workflow.fact_checker]:
            agent._call_llm = Mock(return_value=mock_llm_response)
        
        # Execute
        result = workflow.execute("https://github.com/user/test-repo", "Test repo")
        
        # Assertions
        assert "final_summary" in result
        assert "repository" in result["final_summary"]
        assert "summary" in result["final_summary"]
    
    def test_workflow_builds_graph_correctly(self):
        """Test workflow graph structure."""
        workflow = PublicationAssistantWorkflow()
        
        assert workflow.graph is not None
        assert workflow.repo_analyzer is not None
        assert workflow.metadata_recommender is not None
        assert workflow.content_improver is not None
        assert workflow.reviewer_critic is not None
        assert workflow.fact_checker is not None
    
    def test_synthesize_results(self, sample_state, sample_repo_data):
        """Test result synthesis."""
        workflow = PublicationAssistantWorkflow()
        
        # Setup state
        sample_state["repo_data"] = sample_repo_data
        sample_state["code_structure"] = {
            "quality_score": 75.0,
            "missing_sections": ["Contributing", "Changelog"]
        }
        
        result = workflow._synthesize_results(sample_state)
        
        assert "final_summary" in result
        assert "repository" in result["final_summary"]
        assert "action_items" in result["final_summary"]


@pytest.mark.integration
class TestPublicationAssistant:
    """Integration tests for main application."""
    
    def test_assistant_initialization(self):
        """Test assistant initialization."""
        try:
            assistant = PublicationAssistant()
            assert assistant.workflow is not None
            assert assistant.reports_dir.exists()
        except ValueError:
            # Skip if API keys not configured
            pytest.skip("API keys not configured")
    
    @patch('src.main.PublicationAssistantWorkflow')
    def test_analyze_method(self, mock_workflow):
        """Test analyze method."""
        # Mock workflow
        mock_workflow_instance = Mock()
        mock_workflow_instance.execute.return_value = {
            "final_summary": {
                "repository": {"name": "test", "url": "", "current_score": 75},
                "summary": {"status": "Good", "total_suggestions": 5, "critical_issues": 1},
                "action_items": []
            }
        }
        mock_workflow.return_value = mock_workflow_instance
        
        try:
            assistant = PublicationAssistant()
            result = assistant.analyze("https://github.com/user/repo")
            
            assert "repository" in result
            assert "summary" in result
        except ValueError:
            pytest.skip("API keys not configured")
