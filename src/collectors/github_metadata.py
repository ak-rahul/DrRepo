"""GitHub repository metadata collector (stars, forks, topics, file structure).

Carried over from v1's GitHubTool, fixed to take an injected `Config` instead
of a global singleton, and reshaped into a plain function returning a
`CollectorResult` so it's testable without patching module-level state.
"""

from __future__ import annotations

from typing import Any, Dict

from github import Auth, Github, GithubException

from src.config import Config
from src.models import CollectorResult, CollectorStatus
from src.utils.logger import logger
from src.utils.retry import retry_with_backoff


def parse_repo_path(repo_url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL. Raises ValueError if invalid."""
    if not repo_url:
        raise ValueError("Repository URL cannot be empty")
    if not repo_url.startswith("https://github.com/"):
        raise ValueError("Invalid GitHub URL. Must start with https://github.com/")

    path = repo_url.replace("https://github.com/", "").strip("/")
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid repository path. Expected format: https://github.com/owner/repo")

    return f"{parts[0]}/{parts[1]}"


def _analyze_file_structure(repo) -> Dict[str, bool]:
    structure = {
        "has_tests": False,
        "has_ci": False,
        "has_docs": False,
        "has_license": False,
        "has_contributing": False,
        "has_changelog": False,
    }
    try:
        contents = repo.get_contents("")
        for content in contents:
            name_lower = content.name.lower()
            if name_lower in ("tests", "test", "__tests__", "spec"):
                structure["has_tests"] = True
            if name_lower in (
                ".github",
                ".gitlab-ci.yml",
                ".travis.yml",
                "circle.yml",
                ".circleci",
                "azure-pipelines.yml",
            ):
                structure["has_ci"] = True
            if name_lower in ("docs", "doc", "documentation"):
                structure["has_docs"] = True
            if "license" in name_lower:
                structure["has_license"] = True
            if "contributing" in name_lower:
                structure["has_contributing"] = True
            if "changelog" in name_lower or "history" in name_lower:
                structure["has_changelog"] = True
    except GithubException as e:
        if e.status == 403:
            logger.warning("Rate limit hit while analyzing file structure")
        elif e.status == 404:
            # A real, existing repo with zero commits ("this repository is
            # empty") also 404s here -- that's not the same as the repo
            # itself not existing (checked earlier, by which point stars/
            # forks/readme were already fetched successfully), so this
            # correctly reports "no files found" instead of discarding the
            # whole collector result as "repository not found".
            logger.info("Repository has no files (empty repository)")
        else:
            raise
    return structure


@retry_with_backoff(max_retries=2, initial_delay=1.0, exceptions=(GithubException,))
def _get_readme(repo) -> str:
    try:
        readme = repo.get_readme()
        return str(readme.decoded_content.decode("utf-8"))
    except GithubException as e:
        if e.status == 404:
            return ""
        raise


def collect_github_metadata(repo_url: str, config: Config) -> CollectorResult:
    """Fetch repository metadata, README text, and file structure from the GitHub API."""
    try:
        repo_path = parse_repo_path(repo_url)
    except ValueError as e:
        return CollectorResult(name="github_metadata", status=CollectorStatus.ERROR, detail=str(e))

    try:
        auth = Auth.Token(config.github_token) if config.github_token else None
        gh = Github(auth=auth) if auth else Github()
        repo = gh.get_repo(repo_path)

        readme_content = _get_readme(repo)

        data: Dict[str, Any] = {
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
            "license_spdx_id": repo.license.spdx_id if repo.license else None,
            "created_at": repo.created_at.isoformat(),
            "updated_at": repo.updated_at.isoformat(),
            "pushed_at": repo.pushed_at.isoformat(),
            "size_kb": repo.size,
            "default_branch": repo.default_branch,
            "open_issues": repo.open_issues_count,
            "readme_content": readme_content,
            "file_structure": _analyze_file_structure(repo),
        }
        logger.info(f"Fetched GitHub metadata for {repo.full_name}")
        return CollectorResult(name="github_metadata", status=CollectorStatus.OK, data=data)

    except GithubException as e:
        if e.status == 404:
            return CollectorResult(
                name="github_metadata",
                status=CollectorStatus.ERROR,
                detail=f"Repository not found: {repo_url}",
            )
        if e.status == 403:
            return CollectorResult(
                name="github_metadata",
                status=CollectorStatus.ERROR,
                detail="GitHub API rate limit exceeded or access forbidden",
            )
        return CollectorResult(
            name="github_metadata",
            status=CollectorStatus.ERROR,
            detail=f"GitHub API error (status {e.status}): {e.data}",
        )
    except Exception as e:
        logger.error(f"Unexpected error collecting GitHub metadata: {e}")
        return CollectorResult(name="github_metadata", status=CollectorStatus.ERROR, detail=str(e))
