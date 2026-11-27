"""`get_file_git_history`: recent commits touching a file, via the GitHub API.

Clones are shallow (`--depth 1`), so local `git log` would show one commit;
the API has full history.
"""

from __future__ import annotations

import threading
from typing import Any

from github import GithubException
from langchain_core.tools import tool

from drrepo.collectors.github import make_github_client
from drrepo.config import Config

MAX_COMMITS = 10


def make_git_history_tools(repo_full_name: str, config: Config) -> list[Any]:
    lock = threading.Lock()
    state: dict[str, Any] = {}

    def _repo() -> Any:
        with lock:
            if "repo" not in state:
                state["repo"] = make_github_client(config.github_token).get_repo(repo_full_name)
            return state["repo"]

    @tool
    def get_file_git_history(path: str) -> str:
        """Show the most recent commits that touched a file (sha, date, author, message).

        Args:
            path: File path relative to the repository root, e.g. "src/auth.py".
        """
        clean = path.strip().removeprefix("./")
        if not clean or ".." in clean.split("/"):
            return "ERROR: give a repository-relative file path"
        try:
            lines = []
            for commit in _repo().get_commits(path=clean)[:MAX_COMMITS]:
                author = commit.commit.author
                when = author.date.date().isoformat() if author and author.date else "?"
                who = author.name if author else "unknown"
                message = (
                    (commit.commit.message or "").splitlines()[0][:100]
                    if commit.commit.message
                    else ""
                )
                lines.append(f"{commit.sha[:7]} {when} {who}: {message}")
        except GithubException as e:
            return f"ERROR: GitHub API error ({e.status})"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        return "\n".join(lines) or f"No commit history found for '{clean}'"

    return [get_file_git_history]
