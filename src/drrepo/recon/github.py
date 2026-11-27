"""GitHub API metadata collector: stars, forks, license, activity, README text.

`data` schema (status OK):
    name, full_name, description, url, stars, forks, watchers, language, topics,
    license, license_spdx_id, created_at, updated_at, pushed_at, size_kb,
    default_branch, open_issues, archived, readme_content, file_structure
"""

from __future__ import annotations

from typing import Any

from github import Auth, Github, GithubException

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus, RepoRef

NAME = "github_metadata"
_TIMEOUT_SECONDS = 15


def make_github_client(token: str) -> Github:
    """A PyGithub client with bounded timeouts/retries.

    PyGithub's default retry policy will happily sleep until a rate limit
    resets (potentially an hour); a bounded `retry` keeps a rate-limited run
    failing fast and degrading instead of appearing hung.
    """
    auth = Auth.Token(token) if token else None
    return Github(auth=auth, timeout=_TIMEOUT_SECONDS, retry=2)


def _file_structure(repo: Any) -> dict[str, bool]:
    """Root-level hygiene signals from the API. When a clone exists, the richer
    `repo_layout` collector supersedes this (it can see nested test dirs)."""
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
    except GithubException as e:
        if e.status in (403, 404):  # rate limited, or an empty repository
            return structure
        raise
    for content in contents if isinstance(contents, list) else [contents]:
        name = content.name.lower()
        if name in ("tests", "test", "__tests__", "spec", "testing"):
            structure["has_tests"] = True
        if name in (
            ".github",
            ".gitlab-ci.yml",
            ".travis.yml",
            ".circleci",
            "azure-pipelines.yml",
            "jenkinsfile",
        ):
            structure["has_ci"] = True
        if name in ("docs", "doc", "documentation"):
            structure["has_docs"] = True
        if name.startswith(("license", "licence", "copying")):
            structure["has_license"] = True
        if name.startswith("contributing"):
            structure["has_contributing"] = True
        if name.startswith(("changelog", "changes", "history", "news")):
            structure["has_changelog"] = True
    return structure


def _readme(repo: Any) -> str:
    try:
        return str(repo.get_readme().decoded_content.decode("utf-8", errors="replace"))
    except GithubException as e:
        if e.status == 404:
            return ""
        raise


def collect_github_metadata(repo_url: str, config: Config) -> CollectorResult:
    """Fetch repository metadata, README text, and root file structure."""
    try:
        ref = RepoRef.parse(repo_url)
    except ValueError as e:
        return CollectorResult(name=NAME, status=CollectorStatus.ERROR, detail=str(e))

    try:
        repo = make_github_client(config.github_token).get_repo(ref.full_name)
        data: dict[str, Any] = {
            "name": repo.name,
            "full_name": repo.full_name,
            "description": repo.description or "",
            "url": repo.html_url,
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "watchers": repo.subscribers_count,
            "language": repo.language or "Unknown",
            "topics": repo.get_topics(),
            "license": repo.license.name if repo.license else None,
            "license_spdx_id": repo.license.spdx_id if repo.license else None,
            "created_at": repo.created_at.isoformat() if repo.created_at else None,
            "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
            "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
            "size_kb": repo.size,
            "default_branch": repo.default_branch,
            "open_issues": repo.open_issues_count,
            "archived": bool(repo.archived),
            "readme_content": _readme(repo),
            "file_structure": _file_structure(repo),
        }
    except GithubException as e:
        if e.status == 404:
            detail = f"Repository not found (or private): {ref.full_name}"
        elif e.status in (403, 429):
            detail = (
                "GitHub API rate limit exceeded or access forbidden (set GH_TOKEN to raise limits)"
            )
        elif e.status == 401:
            detail = "GitHub rejected GH_TOKEN (401 Unauthorized)"
        else:
            detail = f"GitHub API error (status {e.status})"
        logger.warning(f"github_metadata: {detail}")
        return CollectorResult(name=NAME, status=CollectorStatus.ERROR, detail=detail)
    except Exception as e:
        logger.error(f"Unexpected error collecting GitHub metadata: {e}")
        return CollectorResult(name=NAME, status=CollectorStatus.ERROR, detail=str(e))

    logger.info(f"Fetched GitHub metadata for {ref.full_name}")
    return CollectorResult(name=NAME, status=CollectorStatus.OK, data=data)
