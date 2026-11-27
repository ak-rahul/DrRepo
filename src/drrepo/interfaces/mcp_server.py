"""DrRepo as a Model Context Protocol (MCP) server.

Lets any MCP client (Claude Desktop, Claude Code, IDE agents) call DrRepo as a
set of tools. Start it with `drrepo mcp` (stdio, the default for desktop
clients) or `drrepo mcp --transport streamable-http`.

Tools
    analyze_repository        full recon -> plan -> investigate -> synthesize run
    get_report                last report for a repo from this server session
    list_reports              reports produced in this session
    get_issues                filter a report's issues by severity/category
    check_package_vulnerabilities   OSV.dev lookup for one exact package version
    analyze_readme_text       README structure metrics for arbitrary markdown
    get_score_history         recorded score history for a repo
    health_check              connectivity of LLM provider, GitHub, OSV.dev
Resources
    drrepo://reports/{owner}/{name}           JSON report
    drrepo://reports/{owner}/{name}/markdown  Markdown report
    drrepo://reports/{owner}/{name}/sarif     SARIF 2.1.0 log
Prompts
    review_repository         guided "audit this repo and plan fixes" prompt

One `AnalysisService` lives for the server's lifetime, so the LLM circuit
breaker and dependency cache carry across tool calls.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

import anyio
import anyio.lowlevel
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError

from drrepo import __version__
from drrepo.agents.tools import lookup_package
from drrepo.config import Config
from drrepo.interfaces.health import check_all
from drrepo.log import logger
from drrepo.models import RepoRef, Severity
from drrepo.recon.readme import analyze_readme
from drrepo.report.exporters import to_json, to_markdown, to_sarif
from drrepo.report.history import load_history
from drrepo.service import AnalysisService

mcp = MCPServer(
    name="drrepo",
    version=__version__,
    instructions=(
        "DrRepo audits public GitHub repositories: static analysis, security and secret "
        "scanning, dependency vulnerabilities and licenses, documentation, and maintainability, "
        "with an LLM lead investigator that deep-dives risky areas using tools. Call "
        "analyze_repository first (it takes 1-5 minutes), then get_issues / resources to drill in."
    ),
)


@lru_cache(maxsize=1)
def get_service() -> AnalysisService:
    return AnalysisService(Config.from_env())


def _summary(report: dict[str, Any], max_issues: int) -> dict[str, Any]:
    return {
        "repository": report.get("repository"),
        "overall_score": report.get("overall_score"),
        "issue_counts": report.get("issue_counts"),
        "category_scores": {
            name: {
                "score": cs["score"] if cs.get("assessed", True) else None,
                "depth": cs.get("investigation_depth"),
                "summary": cs.get("summary"),
                "notes": cs.get("notes", []),
            }
            for name, cs in report.get("category_scores", {}).items()
        },
        "top_issues": [
            {
                k: i.get(k)
                for k in (
                    "severity",
                    "category",
                    "title",
                    "file",
                    "line",
                    "recommendation",
                    "occurrences",
                )
            }
            for i in report.get("issues", [])[:max_issues]
        ],
        "quick_wins": report.get("quick_wins", []),
        "score_history": report.get("score_history"),
        "resources": {
            fmt: f"drrepo://reports/{report.get('repository', {}).get('full_name')}{suffix}"
            for fmt, suffix in (("json", ""), ("markdown", "/markdown"), ("sarif", "/sarif"))
        },
    }


@mcp.tool()
async def analyze_repository(
    repo_url: str,
    ctx: Context,
    description: str = "",
    deep: bool = True,
    max_issues: int = 15,
) -> dict[str, Any]:
    """Audit a public GitHub repository and return scores, top issues, and quick wins.

    Takes 1-5 minutes (clones the repo and runs scanners; deep mode lets an LLM
    investigator read code with tools). The full report is then available via
    get_report or the drrepo://reports/{owner}/{name} resources.

    Args:
        repo_url: e.g. "https://github.com/psf/requests".
        description: Optional context or focus for the investigators ("we care about auth").
        deep: Allow tool-calling deep investigations (False = fast, deterministic pass).
        max_issues: How many of the most severe issues to include inline.
    """
    service = get_service()
    try:
        RepoRef.parse(repo_url)
    except ValueError as e:
        return {"error": str(e)}

    steps = {"n": 0}
    # LangGraph runs parallel nodes in its own thread pool, not in anyio worker
    # threads, so from_thread.run needs an explicit token for this event loop.
    loop_token = anyio.lowlevel.current_token()

    def progress(message: str) -> None:
        # Progress is best-effort: a client that doesn't track progress (or a
        # call made outside a live request) must never abort the analysis.
        steps["n"] += 1
        try:
            anyio.from_thread.run(ctx.report_progress, steps["n"], None, message, token=loop_token)
        except Exception as e:
            logger.debug(f"MCP progress notification failed: {e}")

    # ctx.info() is deprecated in MCP 2 (SEP-2577); logs go to stderr instead.
    logger.info(f"MCP: starting analysis of {repo_url}")
    report = await anyio.to_thread.run_sync(
        lambda: service.analyze(repo_url, description, deep=deep, progress=progress)
    )
    return _summary(report, max(0, min(max_issues, 100)))


def _find_report(repo: str) -> dict[str, Any] | None:
    try:
        return get_service().latest_report(repo)
    except ValueError:  # not a GitHub repository reference
        return None


def _missing(repo: str) -> str:
    return f"No report for {repo!r} in this session; call analyze_repository first"


def _require_report(repo: str) -> dict[str, Any]:
    """For tools: a ToolError becomes an `is_error` result the model can read."""
    report = _find_report(repo)
    if report is None:
        raise ToolError(_missing(repo))
    return report


def _resource_report(owner: str, name: str) -> dict[str, Any]:
    """For resources: MCP 2 maps ResourceNotFoundError to JSON-RPC -32602."""
    if not owner or not name:  # MCP 2 lets `{var}` match an empty segment
        raise ResourceNotFoundError("owner and name are required")
    report = _find_report(f"{owner}/{name}")
    if report is None:
        raise ResourceNotFoundError(_missing(f"{owner}/{name}"))
    return report


@mcp.tool()
def get_report(repo: str, format: Literal["json", "markdown", "summary"] = "summary") -> Any:
    """Return the latest report for a repository analyzed in this session.

    Args:
        repo: Repository URL or "owner/name".
        format: "summary" (compact dict), "json" (full report), or "markdown".
    """
    report = _require_report(repo)
    if format == "markdown":
        return to_markdown(report)
    if format == "json":
        return report
    return _summary(report, 15)


@mcp.tool()
def list_reports() -> list[dict[str, Any]]:
    """List reports produced by this server session, newest first."""
    return get_service().list_reports()


@mcp.tool()
def get_issues(
    repo: str,
    min_severity: Literal["critical", "high", "medium", "low"] = "low",
    category: Literal[
        "documentation", "code_quality", "security", "dependencies", "maintainability"
    ]
    | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Filter the issues of an analyzed repository.

    Args:
        repo: Repository URL or "owner/name".
        min_severity: Only issues at least this severe.
        category: Only issues in this category.
        limit: Maximum number of issues to return.
    """
    report = _require_report(repo)
    threshold = Severity(min_severity).rank
    issues = [
        i
        for i in report.get("issues", [])
        if Severity(i["severity"]).rank <= threshold
        and (category is None or i["category"] == category)
    ]
    return issues[: max(0, min(limit, 500))]


@mcp.tool()
def check_package_vulnerabilities(package: str, ecosystem: str, version: str) -> str:
    """Known vulnerabilities (severity, fixed versions) for one exact package version via OSV.dev.

    Args:
        package: Package name, e.g. "django".
        ecosystem: "PyPI", "npm", "Go", "crates.io", "Maven", "RubyGems", "NuGet", or "Packagist".
        version: Exact version, e.g. "3.2.0".
    """
    service = get_service()
    return lookup_package(package, ecosystem, version, service.config, service.cache)


@mcp.tool()
def analyze_readme_text(markdown: str) -> dict[str, Any]:
    """Structural README metrics (sections, examples, missing essentials, 0-100 score) for any markdown text."""
    return analyze_readme(markdown).data


@mcp.tool()
def get_score_history(repo: str) -> list[dict[str, Any]]:
    """Recorded overall/category scores from previous analyses of a repository (oldest first)."""
    ref = RepoRef.parse(
        repo if "://" in repo or "github.com" in repo else f"https://github.com/{repo}"
    )
    history = load_history(get_service().history_path)
    return [r for r in history if str(r.get("repo_key", "")).lower() == ref.html_url.lower()]


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Check connectivity to the LLM provider, the GitHub API, and OSV.dev (spends no LLM tokens)."""
    status = check_all(get_service().config)
    status["llm_circuit_breaker"] = get_service().breaker_state()
    return status


@mcp.resource("drrepo://reports/{owner}/{name}", mime_type="application/json")
def report_json(owner: str, name: str) -> str:
    """Full JSON report for a repository analyzed in this session."""
    return to_json(_resource_report(owner, name))


@mcp.resource("drrepo://reports/{owner}/{name}/markdown", mime_type="text/markdown")
def report_markdown(owner: str, name: str) -> str:
    """Markdown report for a repository analyzed in this session."""
    return to_markdown(_resource_report(owner, name))


@mcp.resource("drrepo://reports/{owner}/{name}/sarif", mime_type="application/sarif+json")
def report_sarif(owner: str, name: str) -> str:
    """SARIF 2.1.0 log (GitHub code scanning format) for a repository analyzed in this session."""
    return to_sarif(_resource_report(owner, name))


@mcp.prompt()
def review_repository(repo_url: str, focus: str = "") -> str:
    """Audit a repository with DrRepo and turn the findings into a prioritized fix plan."""
    focus_line = f"\nPay particular attention to: {focus}." if focus else ""
    return (
        f"Audit {repo_url} with DrRepo.{focus_line}\n\n"
        "1. Call analyze_repository (deep=true).\n"
        "2. Call get_issues with min_severity='high' and read the evidence for each.\n"
        "3. Produce a prioritized plan: what to fix first and why, grouped by category, with "
        "the file paths DrRepo cited. Flag anything that looks like a false positive.\n"
        "4. End with the quick wins that take under an hour."
    )


def run(
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    if transport == "stdio":
        mcp.run("stdio")
    elif transport == "sse":
        mcp.run("sse", host=host, port=port)
    else:
        mcp.run("streamable-http", host=host, port=port)
