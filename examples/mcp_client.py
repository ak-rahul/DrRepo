"""Drive the DrRepo MCP server from Python, the way an assistant would.

Starts `drrepo mcp` as a stdio subprocess, lists what it offers, runs a fast
(shallow) analysis with progress notifications, then reads the full Markdown
report back through a resource.

    uv run python examples/mcp_client.py https://github.com/pallets/itsdangerous
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, ReadResourceResult, TextContent, TextResourceContents
from pydantic import AnyUrl

from drrepo.models import RepoRef


def text_of(result: CallToolResult | ReadResourceResult) -> str:
    """Join the text parts of a tool result (`content`) or resource read (`contents`)."""
    parts = result.content if isinstance(result, CallToolResult) else result.contents
    return "\n".join(p.text for p in parts if isinstance(p, TextContent | TextResourceContents))


async def on_progress(progress: float, total: float | None, message: str | None) -> None:
    print(f"  · [{progress:.0f}] {message or ''}")


async def run(repo_url: str) -> None:
    # Same interpreter, same environment: the server reads .env like the CLI does.
    server = StdioServerParameters(command=sys.executable, args=["-m", "drrepo", "mcp"])
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        print("Tools:", ", ".join(t.name for t in tools.tools))
        templates = await session.list_resource_templates()
        print("Resources:", ", ".join(t.uriTemplate for t in templates.resourceTemplates))
        prompts = await session.list_prompts()
        print("Prompts:", ", ".join(p.name for p in prompts.prompts))

        print(f"\nanalyze_repository({repo_url}, deep=False)")
        result = await session.call_tool(
            "analyze_repository",
            {"repo_url": repo_url, "deep": False, "max_issues": 5},
            progress_callback=on_progress,
        )
        summary = result.structuredContent or json.loads(text_of(result))
        if "error" in summary:
            raise SystemExit(f"Server refused the URL: {summary['error']}")
        print(json.dumps(summary, indent=2)[:1500])

        repo = RepoRef.parse(repo_url)
        markdown = await session.read_resource(
            AnyUrl(f"drrepo://reports/{repo.owner}/{repo.name}/markdown")
        )
        print("\nFirst lines of the Markdown report resource:")
        print("\n".join(text_of(markdown).splitlines()[:15]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise the DrRepo MCP server.")
    parser.add_argument("repo_url", nargs="?", default="https://github.com/pallets/itsdangerous")
    asyncio.run(run(parser.parse_args().repo_url))


if __name__ == "__main__":
    main()
