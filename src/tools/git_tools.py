"""Read-only commit history inspection for investigator agents.

Queries the GitHub API for a file's commit history rather than running local
`git log`: clones are shallow (`--depth 1`, see repo_clone.py) for speed, so a
local git log would only ever show the single commit present in the shallow
clone. The GitHub API has full history regardless of clone depth.
"""

from __future__ import annotations

from typing import List

from github import Github, GithubException
from langchain_core.tools import tool

from src.config import Config

_MAX_COMMITS = 10


def make_git_history_tools(repo_full_name: str, config: Config) -> List:
    """Build a `get_file_git_history` tool bound to a specific repo (`owner/repo`)."""

    @tool
    def get_file_git_history(path: str) -> str:
        """Show recent commit history for a file (author, date, message).

        Args:
            path: File path relative to the repository root, e.g. "src/main.py".
        """
        try:
            gh = Github(config.github_token) if config.github_token else Github()
            repo = gh.get_repo(repo_full_name)
            commits = repo.get_commits(path=path)

            lines = []
            for commit in commits[:_MAX_COMMITS]:  # type: ignore[var-annotated]  # PyGithub has no type stubs
                author = commit.commit.author.name if commit.commit.author else "unknown"
                commit_date = (
                    commit.commit.author.date.date().isoformat() if commit.commit.author else "?"
                )
                message = commit.commit.message.splitlines()[0][:100]
                lines.append(f"{commit.sha[:7]} {commit_date} {author}: {message}")

            return "\n".join(lines) if lines else f"No commit history found for '{path}'"

        except GithubException as e:
            return f"ERROR: GitHub API error: {e}"
        except Exception as e:
            return f"ERROR: {e}"

    return [get_file_git_history]
