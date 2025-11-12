"""GitHub repository analysis tool."""
from typing import Dict, List, Optional
from github import Github, GithubException
from src.tools.base_tool import BaseTool
from src.utils.config import config
from src.utils.validators import validate_github_url

class GitHubTool(BaseTool):
    """Tool for interacting with GitHub API."""
    
    def __init__(self):
        super().__init__("GitHubTool")
        self.client = Github(config.github_token)
    
    def execute(self, repo_url: str) -> Dict:
        """
        Fetch comprehensive repository data.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            Dictionary containing repo data
        """
        try:
            owner, repo_name = validate_github_url(repo_url)
            repo = self.client.get_repo(f"{owner}/{repo_name}")
            
            # Fetch README
            readme_content = self._fetch_readme(repo)
            
            # Get file structure
            file_structure = self._analyze_file_structure(repo)
            
            # Compile repository data
            repo_data = {
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description or "No description provided",
                "url": repo.html_url,
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "watchers": repo.watchers_count,
                "open_issues": repo.open_issues_count,
                "language": repo.language,
                "topics": repo.get_topics(),
                "license": repo.license.name if repo.license else None,
                "has_wiki": repo.has_wiki,
                "has_issues": repo.has_issues,
                "has_projects": repo.has_projects,
                "created_at": repo.created_at.isoformat(),
                "updated_at": repo.updated_at.isoformat(),
                "pushed_at": repo.pushed_at.isoformat(),
                "default_branch": repo.default_branch,
                "readme_content": readme_content,
                "file_structure": file_structure,
            }
            
            # Get languages
            languages = repo.get_languages()
            repo_data["languages"] = languages
            
            self.logger.info(f"Successfully fetched data for {repo.full_name}")
            return repo_data
            
        except GithubException as e:
            return self._handle_error(e)
        except Exception as e:
            return self._handle_error(e)
    
    def _fetch_readme(self, repo) -> str:
        """Fetch README content."""
        try:
            readme = repo.get_readme()
            return readme.decoded_content.decode('utf-8')
        except:
            return "No README found"
    
    def _analyze_file_structure(self, repo) -> Dict:
        """Analyze repository file structure."""
        structure = {
            "files": [],
            "directories": [],
            "has_tests": False,
            "has_docs": False,
            "has_ci": False,
            "has_requirements": False,
            "has_setup": False,
            "has_docker": False,
            "has_makefile": False,
            "has_contributing": False,
            "has_license": False,
            "has_changelog": False,
        }
        
        try:
            contents = repo.get_contents("")
            
            for content in contents:
                name_lower = content.name.lower()
                
                if content.type == "dir":
                    structure["directories"].append(content.name)
                    
                    # Check for special directories
                    if name_lower in ["tests", "test", "__tests__"]:
                        structure["has_tests"] = True
                    elif name_lower in ["docs", "documentation", ".github"]:
                        structure["has_docs"] = True
                    elif name_lower == ".github":
                        structure["has_ci"] = True
                else:
                    structure["files"].append(content.name)
                    
                    # Check for special files
                    if name_lower in ["requirements.txt", "pipfile", "pyproject.toml", "setup.py"]:
                        structure["has_requirements"] = True
                    elif name_lower in ["setup.py", "setup.cfg"]:
                        structure["has_setup"] = True
                    elif name_lower in ["dockerfile", "docker-compose.yml"]:
                        structure["has_docker"] = True
                    elif name_lower == "makefile":
                        structure["has_makefile"] = True
                    elif name_lower in ["contributing.md", "contributing.rst"]:
                        structure["has_contributing"] = True
                    elif name_lower.startswith("license"):
                        structure["has_license"] = True
                    elif name_lower in ["changelog.md", "changelog.rst", "history.md"]:
                        structure["has_changelog"] = True
            
        except Exception as e:
            self.logger.error(f"Error analyzing file structure: {str(e)}")
        
        return structure
    
    def get_repository_stats(self, repo_url: str) -> Dict:
        """Get repository statistics."""
        try:
            owner, repo_name = validate_github_url(repo_url)
            repo = self.client.get_repo(f"{owner}/{repo_name}")
            
            # Get contributor count
            contributors = repo.get_contributors()
            contributor_count = contributors.totalCount
            
            # Get commit activity
            commit_activity = repo.get_stats_commit_activity()
            
            return {
                "contributors": contributor_count,
                "commit_activity": [
                    {"week": week.week, "total": week.total}
                    for week in (commit_activity or [])[-12:]  # Last 12 weeks
                ]
            }
        except Exception as e:
            return self._handle_error(e)
