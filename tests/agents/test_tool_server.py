"""Investigators call their tools through DrRepo's own MCP tool server."""

import asyncio
from unittest.mock import patch

import pytest
from mcp.client.client import Client

from drrepo.agents.tool_server import ToolServerError, build_tool_server, mcp_tools
from drrepo.config import Config


@pytest.fixture
def clone(tmp_path):
    (tmp_path / "app.py").write_text("def hello(x):\n    return x\n", encoding="utf-8")
    return tmp_path


def test_server_exposes_only_the_families_asked_for(clone):
    async def listing(families):
        server = build_tool_server(families, clone_root=str(clone), config=Config())
        async with Client(server) as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    files = asyncio.run(listing(("files",)))
    assert set(files) == {"read_file", "list_directory", "find_files", "search_code"}
    assert files["read_file"].annotations.read_only_hint is True
    assert "path" in files["read_file"].input_schema["properties"]
    every = asyncio.run(listing(("files", "symbols", "scanners", "dependencies")))
    assert {"find_definition", "outline", "run_scanner_on_path", "query_osv"} <= set(every)
    assert every["query_osv"].annotations.open_world_hint is True


def test_agents_get_langchain_tools_that_call_over_mcp(clone):
    with mcp_tools(("files", "symbols"), clone_root=str(clone), config=Config()) as tools:
        by_name = {t.name: t for t in tools}
        assert by_name["read_file"].invoke({"path": "app.py"}).startswith("    1| def hello")
        assert by_name["read_file"].invoke({"path": "../x"}).startswith("ERROR")  # sandboxed
        assert by_name["find_definition"].invoke({"name": "hello"}) == (
            "app.py:1-2: function hello: def hello(x)"
        )
        with patch("mcp.client.client.Client.call_tool", side_effect=RuntimeError("down")):
            # A failed call is a readable tool error, never an exception in the agent loop.
            assert by_name["read_file"].invoke({"path": "app.py"}) == (
                "ERROR: tool read_file failed (RuntimeError)"
            )


def test_a_server_that_cannot_start_raises_tool_server_error(clone):
    with (
        patch("mcp.client.client.Client.__aenter__", side_effect=OSError("no transport")),
        pytest.raises(ToolServerError, match="no transport"),
        mcp_tools(("files",), clone_root=str(clone), config=Config()),
    ):
        pass
