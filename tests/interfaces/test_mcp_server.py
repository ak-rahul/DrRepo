"""MCP server: tool/resource registration and behavior through MCPServer's own call path (MCP 2)."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from drrepo.interfaces import mcp_server

REPORT = {
    "repository": {"name": "demo", "full_name": "octo/demo", "url": "https://github.com/octo/demo"},
    "overall_score": 77.0,
    "issue_counts": {"critical": 0, "high": 1, "medium": 0, "low": 1},
    "category_scores": {
        "security": {
            "score": 60,
            "assessed": True,
            "investigation_depth": "deep",
            "summary": "s",
            "notes": [],
        }
    },
    "issues": [
        {
            "severity": "high",
            "category": "security",
            "title": "Shell",
            "file": "a.py",
            "line": 1,
            "recommendation": "r",
            "occurrences": 1,
            "source": "bandit",
            "rule_id": "B602",
            "description": "d",
            "locations": [],
        },
        {
            "severity": "low",
            "category": "documentation",
            "title": "Docs",
            "file": None,
            "line": None,
            "recommendation": "r",
            "occurrences": 1,
            "source": "x",
            "rule_id": None,
            "description": "d",
            "locations": [],
        },
    ],
    "quick_wins": ["r"],
    "collector_status": {},
}


@pytest.fixture
def service(monkeypatch):
    svc = MagicMock()
    svc.analyze.return_value = REPORT
    svc.latest_report.side_effect = lambda repo: REPORT if "demo" in repo else None
    svc.list_reports.return_value = [{"repository": "octo/demo"}]
    monkeypatch.setattr(mcp_server, "get_service", lambda: svc)
    return svc


def _result(tool, args):
    return asyncio.run(mcp_server.mcp.call_tool(tool, args))


def _call(tool, args):
    result = _result(tool, args)
    assert not result.is_error, result.content
    structured = result.structured_content
    if isinstance(structured, dict):
        return structured.get("result", structured)
    text = result.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:  # a plain string result, e.g. Markdown
        return text


def _read(uri):
    return next(iter(asyncio.run(mcp_server.mcp.read_resource(uri)))).content


def test_registered_surface():
    async def surface():
        tools = {t.name for t in await mcp_server.mcp.list_tools()}
        templates = {r.uri_template for r in await mcp_server.mcp.list_resource_templates()}
        prompts = {p.name for p in await mcp_server.mcp.list_prompts()}
        return tools, templates, prompts

    tools, templates, prompts = asyncio.run(surface())
    assert tools == {
        "analyze_repository",
        "get_report",
        "list_reports",
        "get_issues",
        "check_package_vulnerabilities",
        "analyze_readme_text",
        "get_score_history",
        "health_check",
    }
    assert "drrepo://reports/{owner}/{name}/sarif" in templates
    assert prompts == {"review_repository"}


def test_analyze_repository_returns_summary(service):
    result = _call(
        "analyze_repository",
        {"repo_url": "https://github.com/octo/demo", "max_issues": 1, "deep": False},
    )
    assert result["overall_score"] == 77.0
    assert [i["title"] for i in result["top_issues"]] == ["Shell"]
    assert result["resources"]["sarif"] == "drrepo://reports/octo/demo/sarif"
    assert service.analyze.call_args.kwargs["deep"] is False


def test_analyze_repository_rejects_bad_url(service):
    assert "error" in _call("analyze_repository", {"repo_url": "https://example.com/x"})
    service.analyze.assert_not_called()


def test_get_issues_filters(service):
    issues = _call("get_issues", {"repo": "octo/demo", "min_severity": "high"})
    assert [i["title"] for i in issues] == ["Shell"]
    assert [
        i["title"] for i in _call("get_issues", {"repo": "octo/demo", "category": "documentation"})
    ] == ["Docs"]


def test_get_report_unknown_repo_is_a_tool_error(service):
    # Called directly, MCPServer raises ToolError; the protocol layer turns it
    # into an `is_error` result the model can read.
    with pytest.raises(ToolError, match="analyze_repository first"):
        _result("get_report", {"repo": "octo/other"})


def test_get_report_formats(service):
    assert _call("get_report", {"repo": "octo/demo"})["overall_score"] == 77.0
    assert _call("get_report", {"repo": "octo/demo", "format": "json"}) == REPORT
    assert _call("get_report", {"repo": "octo/demo", "format": "markdown"}).startswith("# DrRepo")


def test_list_reports_and_health(service, monkeypatch):
    assert _call("list_reports", {}) == [{"repository": "octo/demo"}]
    monkeypatch.setattr(mcp_server, "check_all", lambda _config: {"healthy": True})
    service.breaker_state.return_value = {"state": "closed"}
    assert _call("health_check", {}) == {
        "healthy": True,
        "llm_circuit_breaker": {"state": "closed"},
    }


def test_package_lookup_uses_shared_cache(service, monkeypatch):
    seen = {}

    def lookup(package, ecosystem, version, config, cache):
        seen.update(package=package, cache=cache)
        return "no known vulnerabilities"

    monkeypatch.setattr(mcp_server, "lookup_package", lookup)
    args = {"package": "django", "ecosystem": "PyPI", "version": "3.2.0"}
    assert _call("check_package_vulnerabilities", args) == "no known vulnerabilities"
    assert seen == {"package": "django", "cache": service.cache}


def test_score_history_filters_by_repo(service, monkeypatch):
    history = [
        {"repo_key": "https://github.com/octo/demo", "overall_score": 70},
        {"repo_key": "https://github.com/octo/other", "overall_score": 10},
    ]
    monkeypatch.setattr(mcp_server, "load_history", lambda _path: history)
    assert _call("get_score_history", {"repo": "octo/demo"}) == history[:1]


def test_readme_tool_is_pure():
    data = _call("analyze_readme_text", {"markdown": "# T\n\n## Usage\n\n```\nx\n```\n"})
    assert data["code_block_count"] == 1 and "Usage" not in data["missing_sections"]


def test_report_resources(service):
    assert json.loads(_read("drrepo://reports/octo/demo/sarif"))["version"] == "2.1.0"
    assert json.loads(_read("drrepo://reports/octo/demo"))["overall_score"] == 77.0
    assert _read("drrepo://reports/octo/demo/markdown").startswith("# DrRepo")


@pytest.mark.parametrize("uri", ["drrepo://reports/octo/other", "drrepo://reports//demo/sarif"])
def test_missing_resource_is_not_found(service, uri):
    with pytest.raises(Exception, match=r"analyze_repository first|required"):
        _read(uri)


def test_prompt_mentions_focus():
    result = asyncio.run(
        mcp_server.mcp.get_prompt(
            "review_repository", {"repo_url": "https://github.com/a/b", "focus": "auth"}
        )
    )
    assert "auth" in result.messages[0].content.text


def test_progress_reaches_client_from_foreign_threads(service):
    """LangGraph runs parallel nodes in its own thread pool; progress from those
    threads (not anyio workers) must still be delivered, not silently dropped."""
    import threading

    received: list[str] = []

    class FakeContext:
        async def report_progress(self, _progress, _total, message):
            received.append(message)

    def analyze(*_args, progress, **_kwargs):
        progress("from the worker thread")
        worker = threading.Thread(target=progress, args=("from a foreign thread",))
        worker.start()
        worker.join()
        return REPORT

    service.analyze.side_effect = analyze
    asyncio.run(mcp_server.analyze_repository("https://github.com/octo/demo", FakeContext()))
    assert received == ["from the worker thread", "from a foreign thread"]


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        ("stdio", (("stdio",), {})),
        ("sse", (("sse",), {"host": "10.0.0.5", "port": 9000})),
        ("streamable-http", (("streamable-http",), {"host": "10.0.0.5", "port": 9000})),
    ],
)
def test_run_passes_host_and_port_to_http_transports(monkeypatch, transport, expected):
    calls = []
    monkeypatch.setattr(mcp_server.mcp, "run", lambda *a, **k: calls.append((a, k)))
    mcp_server.run(transport, host="10.0.0.5", port=9000)
    assert calls == [expected]
