"""Web search tool using Tavily API."""
from typing import List, Dict
from tavily import TavilyClient
from src.tools.base_tool import BaseTool
from src.utils.config import config

class WebSearchTool(BaseTool):
    """Tool for web search functionality."""
    
    def __init__(self):
        super().__init__("WebSearchTool")
        self.client = TavilyClient(api_key=config.tavily_api_key)
    
    def execute(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Execute web search.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of search results
        """
        try:
            response = self.client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_answer=True
            )
            
            self.logger.info(f"Search completed for: {query}")
            return response.get('results', [])
            
        except Exception as e:
            return [self._handle_error(e)]
    
    def find_similar_repositories(self, language: str, topics: List[str]) -> List[Dict]:
        """Find similar successful repositories."""
        query = f"top GitHub {language} repositories {' '.join(topics[:3])} stars trending"
        return self.execute(query, max_results=3)
    
    def get_readme_best_practices(self) -> List[Dict]:
        """Get best practices for README files."""
        query = "GitHub README best practices professional structure 2025"
        return self.execute(query, max_results=3)
    
    def search_documentation_standards(self, language: str) -> List[Dict]:
        """Search for documentation standards for specific language."""
        query = f"{language} documentation standards best practices 2025"
        return self.execute(query, max_results=3)
