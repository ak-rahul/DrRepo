"""Web Search Tool using Tavily API."""
from typing import List, Dict
from tavily import TavilyClient
from src.utils.config import config
from src.utils.logger import logger


class WebSearchTool:
    """Tool for web search using Tavily API."""
    
    def __init__(self):
        """Initialize Tavily client."""
        self.logger = logger
        self.client = TavilyClient(api_key=config.tavily_api_key)
    
    def search_similar_repositories(
        self,
        language: str,
        description: str
    ) -> List[Dict]:
        """Search for similar successful repositories.
        
        Args:
            language: Programming language
            description: Repository description
        
        Returns:
            List of similar repository results
        """
        try:
            query = f"top GitHub {language} repositories {description[:50]} stars trending"
            
            response = self.client.search(
                query=query,
                max_results=5,
                search_depth="basic"
            )
            
            self.logger.info(f"Search completed for: {query}")
            return response.get("results", [])
            
        except Exception as e:
            self.logger.error(f"Search error: {str(e)}")
            return []
    
    def get_readme_best_practices(self) -> List[Dict]:
        """Get README best practices from web search.
        
        Returns:
            List of best practice results
        """
        try:
            query = "GitHub README best practices professional structure 2025"
            
            response = self.client.search(
                query=query,
                max_results=3,
                search_depth="basic"
            )
            
            self.logger.info(f"Search completed for: {query}")
            return response.get("results", [])
            
        except Exception as e:
            self.logger.error(f"Search error: {str(e)}")
            return []
