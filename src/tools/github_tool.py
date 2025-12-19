"""GitHub API Tool for fetching repository data."""

from typing import Dict, Optional

from github import Github, GithubException

from src.utils.config import config
from src.utils.logger import logger
from src.utils.retry import retry_with_backoff, retry_on_rate_limit
from src.utils.exceptions import (
    RepositoryNotFoundError,
    RateLimitError,
    APIConnectionError,
    ValidationError,
    ToolExecutionError
)


class GitHubTool:
    """Tool for interacting with GitHub API with automatic retry on failures."""

    def __init__(self):
        """Initialize GitHub API client."""
        self.logger = logger
        
        if not config.github_token:
            raise ValidationError("GitHub token not configured. Set GH_TOKEN in .env")
        
        self.github = Github(config.github_token)

    @retry_with_backoff(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
        exceptions=(GithubException, ConnectionError, TimeoutError)
    )
    def execute(self, repo_url: str) -> Dict:
        """Fetch repository data from GitHub with automatic retry.

        Args:
            repo_url: GitHub repository URL

        Returns:
            Dictionary containing repository data

        Raises:
            ValidationError: If URL is invalid
            RepositoryNotFoundError: If repository doesn't exist (404)
            RateLimitError: If API rate limit exceeded (403)
            APIConnectionError: If GitHub API connection fails
            ToolExecutionError: If tool execution fails
            
        Retry Strategy:
            - Max 3 retries with exponential backoff
            - Initial delay: 1s, then 2s, then 4s
            - Retries on: GithubException, ConnectionError, TimeoutError
        """
        try:
            # Extract owner and repo name from URL
            repo_path = self._parse_repo_url(repo_url)

            # Fetch repository (with automatic retry on failure)
            repo = self.github.get_repo(repo_path)

            # Fetch README (with automatic retry on failure)
            readme_content = self._get_readme(repo)

            # Build comprehensive repo data
            repo_data = {
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description or "",
                "url": repo.html_url,
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "watchers": repo.watchers_count,
                "language": repo.language or "Unknown",
                "topics": repo.get_topics(),
                "license": repo.license.name if repo.license else None,
                "created_at": repo.created_at.isoformat(),
                "updated_at": repo.updated_at.isoformat(),
                "pushed_at": repo.pushed_at.isoformat(),
                "size": repo.size,
                "default_branch": repo.default_branch,
                "open_issues": repo.open_issues_count,
                "readme_content": readme_content,
                "file_structure": self._analyze_file_structure(repo)
            }

            self.logger.info(f"Successfully fetched data for {repo.full_name}")
            return repo_data

        except GithubException as e:
            # Convert GitHub exceptions to custom exceptions
            if e.status == 404:
                self.logger.error(f"Repository not found: {repo_url}")
                raise RepositoryNotFoundError(
                    f"Repository not found: {repo_url}. "
                    f"Please check the URL and ensure the repository exists."
                ) from e
            
            elif e.status == 403:
                # Check if it's a rate limit issue
                if "rate limit" in str(e).lower():
                    self.logger.error("GitHub API rate limit exceeded")
                    raise RateLimitError(
                        "GitHub API rate limit exceeded. "
                        "Please wait and try again, or check your GitHub token. "
                        "Authenticated requests have a limit of 5000/hour."
                    ) from e
                else:
                    self.logger.error("GitHub API access forbidden")
                    raise APIConnectionError(
                        "Access forbidden. Check your GitHub token permissions."
                    ) from e
            
            elif e.status == 401:
                self.logger.error("GitHub API authentication failed")
                raise ValidationError(
                    "Invalid GitHub token. Please check your GH_TOKEN in .env"
                ) from e
            
            else:
                self.logger.error(f"GitHub API error: {str(e)}")
                raise APIConnectionError(
                    f"GitHub API error (status {e.status}): {str(e)}"
                ) from e
        
        except (ConnectionError, TimeoutError) as e:
            self.logger.error(f"Network error: {str(e)}")
            raise APIConnectionError(
                f"Network error connecting to GitHub: {str(e)}"
            ) from e
        
        except Exception as e:
            self.logger.error(f"Unexpected error in GitHubTool: {str(e)}")
            raise ToolExecutionError(
                "GitHubTool",
                f"Unexpected error: {str(e)}",
                original_error=e
            ) from e

    def _parse_repo_url(self, repo_url: str) -> str:
        """Parse GitHub URL to extract owner/repo.

        Args:
            repo_url: GitHub repository URL

        Returns:
            Repository path in format "owner/repo"

        Raises:
            ValidationError: If URL format is invalid
        """
        if not repo_url:
            raise ValidationError("Repository URL cannot be empty")
        
        if not repo_url.startswith('https://github.com/'):
            raise ValidationError(
                "Invalid GitHub URL. Must start with https://github.com/"
            )

        # Remove https://github.com/ and any trailing slashes
        path = repo_url.replace('https://github.com/', '').strip('/')

        # Should be in format owner/repo
        parts = path.split('/')
        if len(parts) < 2:
            raise ValidationError(
                "Invalid repository path. Expected format: https://github.com/owner/repo"
            )

        return f"{parts[0]}/{parts[1]}"

    @retry_with_backoff(
        max_retries=2,
        backoff_factor=2.0,
        exceptions=(GithubException,)
    )
    def _get_readme(self, repo) -> str:
        """Fetch README content from repository with retry.

        Args:
            repo: PyGithub repository object

        Returns:
            README content as string (empty string if not found)
            
        Retry Strategy:
            - Max 2 retries with exponential backoff
            - Initial delay: 1s (default), then 2s
            - Retries on: GithubException
        """
        try:
            readme = repo.get_readme()
            content = readme.decoded_content.decode('utf-8')
            return content
        except GithubException as e:
            if e.status == 404:
                self.logger.warning(f"No README found for {repo.full_name}")
                return ""
            # Re-raise other GithubExceptions for retry
            raise
        except Exception as e:
            self.logger.error(f"Error fetching README: {str(e)}")
            return ""

    @retry_with_backoff(
        max_retries=2,
        backoff_factor=2.0,
        exceptions=(GithubException,)
    )
    def _analyze_file_structure(self, repo) -> Dict:
        """Analyze repository file structure with retry.

        Args:
            repo: PyGithub repository object

        Returns:
            Dictionary with file structure analysis
            
        Retry Strategy:
            - Max 2 retries with exponential backoff
            - Handles rate limits gracefully
        """
        structure = {
            "has_tests": False,
            "has_ci": False,
            "has_docs": False,
            "has_license": False,
            "has_contributing": False,
            "has_changelog": False
        }

        try:
            # Get root contents
            contents = repo.get_contents("")

            for content in contents:
                name_lower = content.name.lower()

                # Check for test directories
                if name_lower in ['tests', 'test', '__tests__', 'spec']:
                    structure["has_tests"] = True

                # Check for CI/CD
                if name_lower in ['.github', '.gitlab-ci.yml', '.travis.yml',
                                  'circle.yml', '.circleci', 'azure-pipelines.yml']:
                    structure["has_ci"] = True

                # Check for docs
                if name_lower in ['docs', 'doc', 'documentation']:
                    structure["has_docs"] = True

                # Check for license
                if 'license' in name_lower:
                    structure["has_license"] = True

                # Check for contributing guide
                if 'contributing' in name_lower:
                    structure["has_contributing"] = True

                # Check for changelog
                if 'changelog' in name_lower or 'history' in name_lower:
                    structure["has_changelog"] = True

        except GithubException as e:
            if e.status == 403:
                self.logger.warning(f"Rate limit hit while analyzing file structure")
                # Return partial structure instead of failing completely
                return structure
            # Re-raise for retry
            raise
        except Exception as e:
            self.logger.warning(f"Error analyzing file structure: {str(e)}")

        return structure
