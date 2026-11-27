"""MCP server: tool/resource registration and behavior through FastMCP's own call path."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

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


def _call(tool, args):
    content, structured = asyncio.run(mcp_server.mcp.call_tool(tool, args))
    return (
        structured.get("result", structured)
        if isinstance(structured, dict)
        else json.loads(content[0].text)
    )


def test_registered_surface():
    async def surface():
        tools = {t.name for t in await mcp_server.mcp.list_tools()}
        templates = {r.uriTemplate for r in await mcp_server.mcp.list_resource_templates()}
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


def test_get_report_unknown_repo_errors(service):
    with pytest.raises(Exception, match="analyze_repository first"):
        asyncio.run(mcp_server.mcp.call_tool("get_report", {"repo": "octo/other"}))


def test_readme_tool_is_pure():
    data = _call("analyze_readme_text", {"markdown": "# T\n\n## Usage\n\n```\nx\n```\n"})
    assert data["code_block_count"] == 1 and "Usage" not in data["missing_sections"]


def test_sarif_resource(service):
    contents = asyncio.run(mcp_server.mcp.read_resource("drrepo://reports/octo/demo/sarif"))
    assert json.loads(next(iter(contents)).content)["version"] == "2.1.0"


def test_prompt_mentions_focus():
    result = asyncio.run(
        mcp_server.mcp.get_prompt(
            "review_repository", {"repo_url": "https://github.com/a/b", "focus": "auth"}
        )
    )
    assert "auth" in result.messages[0].content.text
