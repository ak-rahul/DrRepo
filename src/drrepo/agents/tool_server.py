"""The investigation tools as an MCP server, and the bridge agents use to call it.

Investigator tools are defined once (`agents/tools.py`) and served over the
Model Context Protocol by `build_tool_server`. `mcp_tools()` starts the server
for one investigation and connects an MCP client to it in memory (no
subprocess, no network). The agent sees the server's tools as LangChain tools
and picks them by their descriptions; every call is an MCP `tools/call`, so the
agent is limited to exactly what the server exposes for its category. The
server is internal to DrRepo's agents; nothing outside an investigation connects to it.

Which tools a server exposes is decided by the category's tool families
(`Analyst.tool_families`), so a documentation investigator never sees scanner
or symbol tools. All tools stay read-only and sandboxed to the clone; arguments
are still treated as hostile by the tool implementations themselves.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.tools import StructuredTool
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from drrepo import __version__
from drrepo.agents.symbols import SymbolIndex
from drrepo.agents.tools import build_tools
from drrepo.config import Config
from drrepo.errors import DrRepoError
from drrepo.log import logger
from drrepo.recon.dependencies import DependencyLookupCache

SERVER_NAME = "drrepo-investigation"
CONNECT_TIMEOUT_SECONDS = 15.0
# Tools whose results come from outside the clone (OSV.dev, the GitHub API).
_OPEN_WORLD = {"query_osv", "get_file_git_history"}


class ToolServerError(DrRepoError):
    """The in-memory MCP tool server could not be started or reached."""


def build_tool_server(
    families: tuple[str, ...] | list[str],
    *,
    clone_root: str,
    config: Config,
    cache: DependencyLookupCache | None = None,
    repo_full_name: str | None = None,
    symbol_index: SymbolIndex | None = None,
) -> MCPServer:
    """An MCP server exposing the investigation tools of `families` for one clone."""
    server = MCPServer(
        name=SERVER_NAME,
        version=__version__,
        instructions=(
            "Read-only tools for auditing one repository checkout: read and search files, "
            "navigate symbols, re-run scanners, look up advisories, and read git history. "
            "Paths are relative to the repository root."
        ),
    )
    for tool in build_tools(
        families,
        clone_root=clone_root,
        config=config,
        cache=cache,
        repo_full_name=repo_full_name,
        symbol_index=symbol_index,
    ):
        server.add_tool(
            tool.func,
            name=tool.name,
            description=tool.description,
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                open_world_hint=tool.name in _OPEN_WORLD,
            ),
            structured_output=False,
        )
    return server


def _text(result: Any) -> str:
    parts = [getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text"]
    text = "\n".join(p for p in parts if p)
    return f"ERROR: {text}" if result.is_error and not text.startswith("ERROR") else text


class MCPToolSession:
    """An MCP client connected in memory to `server`, on a private event-loop thread.

    The investigator's agent loop is synchronous, so each LangChain tool call
    is handed to that loop and waited for, with a timeout.
    """

    def __init__(self, server: MCPServer, call_timeout_seconds: float):
        self._server = server
        self._timeout = call_timeout_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._tools: list[Any] = []
        self._thread = threading.Thread(target=self._run, daemon=True, name="drrepo-mcp-tools")

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as e:  # surfaced to the caller by start()
            self._error = e
            self._ready.set()

    async def _serve(self) -> None:
        from mcp.client.client import Client

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        async with Client(self._server) as client:
            self._client = client
            self._tools = list((await client.list_tools()).tools)
            self._ready.set()
            await self._stop.wait()

    def start(self) -> MCPToolSession:
        self._thread.start()
        if not self._ready.wait(CONNECT_TIMEOUT_SECONDS) or self._error is not None:
            reason = self._error or TimeoutError("no response")
            raise ToolServerError(f"MCP tool server unavailable: {type(reason).__name__}: {reason}")
        return self

    def close(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """One `tools/call`. Failures come back as an "ERROR: ..." result the agent can
        read and work around, like any other tool error; they never end the loop."""
        if self._loop is None or self._client is None:
            return "ERROR: the MCP tool server is not connected"
        future = asyncio.run_coroutine_threadsafe(
            self._client.call_tool(name, arguments), self._loop
        )
        try:
            return _text(future.result(timeout=self._timeout))
        except TimeoutError:
            future.cancel()
            return f"ERROR: tool {name} timed out after {self._timeout:.0f}s"
        except Exception as e:
            logger.warning(f"MCP call {name} failed: {type(e).__name__}: {e}")
            return f"ERROR: tool {name} failed ({type(e).__name__})"

    def langchain_tools(self) -> list[StructuredTool]:
        """The server's tools as LangChain tools; each call is an MCP `tools/call`."""
        tools = []
        for spec in self._tools:

            def run(_name: str = spec.name, **kwargs: Any) -> str:
                return self.call(_name, kwargs)

            tools.append(
                StructuredTool.from_function(
                    func=run,
                    name=spec.name,
                    description=spec.description or spec.name,
                    args_schema=spec.input_schema,
                )
            )
        return tools


@contextmanager
def mcp_tools(
    families: tuple[str, ...] | list[str],
    *,
    clone_root: str,
    config: Config,
    cache: DependencyLookupCache | None = None,
    repo_full_name: str | None = None,
    symbol_index: SymbolIndex | None = None,
) -> Iterator[list[StructuredTool]]:
    """LangChain tools backed by an in-memory MCP tool server for one investigation.

    Raises `ToolServerError` if the server can't be started; the caller decides
    how to degrade.
    """
    server = build_tool_server(
        families,
        clone_root=clone_root,
        config=config,
        cache=cache,
        repo_full_name=repo_full_name,
        symbol_index=symbol_index,
    )
    session = MCPToolSession(server, call_timeout_seconds=config.collector_timeout_seconds + 10)
    session.start()
    try:
        yield session.langchain_tools()
    finally:
        session.close()
        logger.debug("MCP tool session closed")
