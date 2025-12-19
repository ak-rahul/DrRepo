"""Web Search Tool using Tavily API."""

from typing import List, Dict

from tavily import TavilyClient

from src.utils.config import config
from src.utils.logger import logger
from src.utils.retry import retry_with_backoff, retry_on_rate_limit
from src.utils.exceptions import (
    APIConnectionError,
    RateLimitError,
    ValidationError,
    ToolExecutionError
)


class WebSearchTool:
    """Tool for web search using Tavily API with automatic retry on failures."""

    def __init__(self):
        """Initialize Tavily client."""
        self.logger = logger
        
        if not config.tavily_api_key:
            raise ValidationError("Tavily API key not configured. Set TAVILY_API_KEY in .env")
        
        self.client = TavilyClient(api_key=config.tavily_api_key)

    @retry_on_rate_limit(max_retries=3, initial_delay=30.0)
    def search_similar_repositories(
        self,
        language: str,
        description: str
    ) -> List[Dict]:
        """Search for similar successful repositories with retry on rate limits.

        Args:
            language: Programming language
            description: Repository description

        Returns:
            List of similar repository results

        Raises:
            RateLimitError: If API rate limit exceeded
            APIConnectionError: If search fails
            
        Retry Strategy:
            - Max 3 retries with rate limit handling
            - Initial delay: 30s (suitable for API rate limits)
            - Backoff factor: 1.5x
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
            error_msg = str(e).lower()
            
            # Check if it's a rate limit error
            if "rate limit" in error_msg or "429" in error_msg:
                self.logger.error("Tavily API rate limit exceeded")
                raise RateLimitError(
                    "Tavily search API rate limit exceeded. Please try again later."
                ) from e
            
            # Other API errors
            self.logger.error(f"Tavily search error: {str(e)}")
            
            # Return empty list instead of failing workflow
            return []

    @retry_on_rate_limit(max_retries=3, initial_delay=30.0)
    def get_readme_best_practices(self) -> List[Dict]:
        """Get README best practices from web search with retry.

        Returns:
            List of best practice results

        Raises:
            RateLimitError: If API rate limit exceeded
            
        Retry Strategy:
            - Max 3 retries with rate limit handling
            - Initial delay: 30s
            - Suitable for API rate limit scenarios
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
            error_msg = str(e).lower()
            
            if "rate limit" in error_msg or "429" in error_msg:
                self.logger.error("Tavily API rate limit exceeded")
                raise RateLimitError(
                    "Tavily search API rate limit exceeded. Please try again later."
                ) from e
            
            self.logger.error(f"Tavily search error: {str(e)}")
            return []

    @retry_with_backoff(
        max_retries=2,
        backoff_factor=2.0,
        initial_delay=5.0,
        exceptions=(ConnectionError, TimeoutError)
    )
    def search_generic(self, query: str, max_results: int = 5) -> List[Dict]:
        """Generic search with retry for network errors.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of search results

        Raises:
            ValidationError: If query is empty
            APIConnectionError: If network error occurs
            
        Retry Strategy:
            - Max 2 retries for network errors
            - Initial delay: 5s
            - Suitable for transient network issues
        """
        if not query or not query.strip():
            raise ValidationError("Search query cannot be empty")
        
        try:
            response = self.client.search(
                query=query,
                max_results=max_results,
                search_depth="basic"
            )

            self.logger.info(f"Generic search completed for: {query}")
            return response.get("results", [])

        except (ConnectionError, TimeoutError) as e:
            self.logger.error(f"Network error during search: {str(e)}")
            raise APIConnectionError(
                f"Network error connecting to Tavily API: {str(e)}"
            ) from e
        
        except Exception as e:
            self.logger.error(f"Tavily search error: {str(e)}")
            raise ToolExecutionError(
                "WebSearchTool",
                f"Search failed: {str(e)}",
                original_error=e
            ) from e
