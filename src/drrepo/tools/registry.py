"""Assemble the tool set for one investigation from an analyst's tool families."""

from __future__ import annotations

from typing import Any

from drrepo.config import Config
from drrepo.core.cache import DependencyLookupCache

TOOL_FAMILIES = ("files", "scanners", "dependencies", "git_history")


def build_tools(
    families: tuple[str, ...] | list[str],
    *,
    clone_root: str | None,
    config: Config,
    cache: DependencyLookupCache | None = None,
    repo_full_name: str | None = None,
) -> list[Any]:
    """LangChain tools for the requested families.

    Families that need something unavailable are silently omitted (no clone ->
    no file/scanner tools; no `owner/repo` -> no git history), so the agent is
    only ever offered tools that can work.
    """
    from drrepo.tools.dependencies import make_dependency_tools
    from drrepo.tools.files import make_file_tools
    from drrepo.tools.git_history import make_git_history_tools
    from drrepo.tools.scanners import make_scan_tools

    unknown = set(families) - set(TOOL_FAMILIES)
    if unknown:
        raise ValueError(f"Unknown tool families: {sorted(unknown)}")

    tools: list[Any] = []
    if "files" in families and clone_root:
        tools += make_file_tools(clone_root)
    if "scanners" in families and clone_root:
        tools += make_scan_tools(clone_root, config)
    if "dependencies" in families:
        tools += make_dependency_tools(config, cache)
    if "git_history" in families and repo_full_name:
        tools += make_git_history_tools(repo_full_name, config)
    return tools
