# MCP server

`drrepo mcp` exposes DrRepo over the [Model Context Protocol](https://modelcontextprotocol.io), so an assistant can audit a repository and work through the findings itself.

## Client setup

**Claude Desktop / any stdio client** (`claude_desktop_config.json`; template in `examples/mcp_client_config.json`):

```json
{
  "mcpServers": {
    "drrepo": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/DrRepo", "run", "drrepo", "mcp"],
      "env": { "GROQ_API_KEY": "...", "GH_TOKEN": "..." }
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add drrepo -- uv --directory /absolute/path/to/DrRepo run drrepo mcp
```

**Remote / HTTP:** `drrepo mcp --transport streamable-http --host 0.0.0.0 --port 8765` serves at `http://host:8765/mcp` (also available through `docker compose --profile mcp up`). Put it behind your own auth before exposing it: the server has no authentication of its own, and every call can trigger a clone and LLM spend.

With stdio transport, stdout belongs to the protocol. All DrRepo logging goes to stderr and the log file.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `analyze_repository` | `repo_url`, `description=""`, `deep=true`, `max_issues=15` | summary: scores, top issues, quick wins, resource URIs. Takes 1–5 min and streams MCP progress notifications |
| `get_report` | `repo`, `format=summary\|json\|markdown` | latest report from this server session |
| `list_reports` | — | reports produced in this session |
| `get_issues` | `repo`, `min_severity=low`, `category=null`, `limit=50` | filtered issue list with evidence and locations |
| `check_package_vulnerabilities` | `package`, `ecosystem`, `version` | OSV advisories with severity and fixed versions |
| `analyze_readme_text` | `markdown` | README metrics for any text (no network) |
| `get_score_history` | `repo` | recorded scores from previous runs |
| `health_check` | — | provider, GitHub, and OSV connectivity, plus circuit breaker state |

`repo` accepts a URL or `owner/name`. Reports stay in memory for the server's lifetime (the 20 most recent).

## Resources

| URI | MIME type |
|---|---|
| `drrepo://reports/{owner}/{name}` | `application/json` |
| `drrepo://reports/{owner}/{name}/markdown` | `text/markdown` |
| `drrepo://reports/{owner}/{name}/sarif` | `application/sarif+json` |

## Prompts

`review_repository(repo_url, focus="")` walks the assistant through four steps: analyze, pull high-severity issues, build a prioritized fix plan with file paths, and list quick wins.

## Notes

- One `AnalysisService` lives for the server process, so the LLM circuit breaker and dependency cache carry across tool calls.
- Progress notifications are best-effort. A client that doesn't support them never causes an analysis to fail.
