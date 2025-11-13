"""GitHub API Tool for fetching repository data."""
from typing import Dict, Optional
import os
from github import Github, GithubException
from src.utils.config import config
from src.utils.logger import logger


class GitHubTool:
    """Tool for interacting with GitHub API."""
    
    def __init__(self):
        """Initialize GitHub API client."""
        self.logger = logger
        self.github = Github(config.github_token)
    
    def execute(self, repo_url: str) -> Dict:
        """Fetch repository data from GitHub.
        
        Args:
            repo_url: GitHub repository URL
        
        Returns:
            Dictionary containing repository data
        
        Raises:
            ValueError: If URL is invalid
            GithubException: If API call fails
        """
        try:
            # Extract owner and repo name from URL
            repo_path = self._parse_repo_url(repo_url)
            
            # Fetch repository
            repo = self.github.get_repo(repo_path)
            
            # Fetch README
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
            self.logger.error(f"GitHub API error: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching repository data: {str(e)}")
            raise
    
    def _parse_repo_url(self, repo_url: str) -> str:
        """Parse GitHub URL to extract owner/repo.
        
        Args:
            repo_url: GitHub repository URL
        
        Returns:
            Repository path in format "owner/repo"
        
        Raises:
            ValueError: If URL format is invalid
        """
        if not repo_url.startswith('https://github.com/'):
            raise ValueError("Invalid GitHub URL")
        
        # Remove https://github.com/ and any trailing slashes
        path = repo_url.replace('https://github.com/', '').strip('/')
        
        # Should be in format owner/repo
        parts = path.split('/')
        if len(parts) < 2:
            raise ValueError("Invalid repository path")
        
        return f"{parts[0]}/{parts[1]}"
    
    def _get_readme(self, repo) -> str:
        """Fetch README content from repository.
        
        Args:
            repo: PyGithub repository object
        
        Returns:
            README content as string
        """
        try:
            readme = repo.get_readme()
            content = readme.decoded_content.decode('utf-8')
            return content
        except GithubException:
            self.logger.warning(f"No README found for {repo.full_name}")
            return ""
        except Exception as e:
            self.logger.error(f"Error fetching README: {str(e)}")
            return ""
    
    def _analyze_file_structure(self, repo) -> Dict:
        """Analyze repository file structure.
        
        Args:
            repo: PyGithub repository object
        
        Returns:
            Dictionary with file structure analysis
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
        
        except Exception as e:
            self.logger.warning(f"Error analyzing file structure: {str(e)}")
        
        return structure
