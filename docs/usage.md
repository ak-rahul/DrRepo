# Usage

## Install

```bash
uv sync                  # creates .venv with locked dependencies (incl. ruff, bandit, semgrep)
cp .env.example .env     # set GROQ_API_KEY; GH_TOKEN recommended
uv run drrepo doctor     # verifies git, scanners, config, connectivity
```

`git` must be on `PATH`. Everything else is installed by uv.

## CLI

```bash
uv run drrepo https://github.com/owner/repo           # shorthand for `analyze`
uv run drrepo analyze https://github.com/owner/repo \
    --description "We're adopting this; focus on auth" \
    --format json,md,sarif -o reports/ --top 15
```

| Flag | Effect |
|---|---|
| `-d, --description` | context passed to the planner and investigators |
| `--shallow` | no deep investigations for this run |
| `--format` | any of `json,md,sarif`; `''` writes nothing |
| `-o, --output-dir` | default `reports/`. Files are named `<owner>__<repo>_<timestamp>.<ext>` |
| `--json` | print the full JSON report to stdout (progress stays on stderr) |
| `--fail-under N` | exit code 3 if the overall score is below N |
| `--no-history` | don't compare with or record into `reports/history.json` |
| `-q` / `-v` | quiet / debug logs on the console |
| `--env-file`, `--log-file` | alternative `.env` / log path (`''` disables) |

Exit codes: `0` ok, `1` runtime error, `2` usage or configuration error, `3` below `--fail-under`, `130` interrupted.

Other commands:

```bash
uv run drrepo ui [--port 8501] [--headless]         # Streamlit UI
uv run drrepo mcp [--transport stdio|sse|streamable-http]   # see MCP server below
uv run drrepo health [--json]                       # LLM provider / GitHub / OSV connectivity
uv run drrepo doctor [--offline]                    # full local diagnostics
uv run drrepo health-api [--port 8000]              # FastAPI health endpoint
```

## Web UI

`uv run drrepo ui` opens http://localhost:8501. Enter a URL and optional context, and toggle deep investigation in the sidebar. While the analysis runs you see live progress. The results page has:

- the overall score and grade, with deltas against the previous analysis of the same repository
- per-category scores (🕵️ marks deep-investigated categories; `n/a` marks unassessable ones)
- tabs: **Summary** (narratives, notes, quick wins), **Issues** (filter by severity and category), **How it investigated** (the planner's rationale and every tool call with its output), **Raw data** (collector status and full JSON)
- JSON, Markdown, and SARIF downloads

## Python

```python
from pathlib import Path

from drrepo.config import Config
from drrepo.service import AnalysisService, save_report

service = AnalysisService(Config.from_env())
report = service.analyze("https://github.com/psf/requests", deep=True, progress=print)
print(report["overall_score"], report["issue_counts"])
save_report(report, output_dir=Path("reports"), formats=("json", "sarif"))
```

Reuse one `AnalysisService` for many analyses. The circuit breaker and dependency cache are shared; each run gets a fresh token budget. See [examples/](../examples/README.md): `compare_repositories.py` ranks several repositories, `policy_gate.py` applies a custom CI policy, and `custom_collector.py` adds a collector to the pipeline.

## Docker

```bash
docker compose up                                   # UI on :8501
docker compose --profile api --profile mcp up       # + health API :8000, MCP :8765/mcp
docker compose run --rm ui drrepo analyze https://github.com/psf/requests --format md
```

The image runs as a non-root user, contains `git`, and reads credentials from `.env` at runtime. None are baked in. `reports/` and `logs/` are mounted volumes.

## In CI: gate and code scanning

```yaml
- uses: astral-sh/setup-uv@v6
- run: uvx --from git+https://github.com/ak-rahul/DrRepo drrepo analyze "https://github.com/${{ github.repository }}" --shallow --format sarif -o drrepo --fail-under 60
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: drrepo
```

A complete workflow (weekly schedule, permissions, Markdown artifact) is in [examples/github-workflow.yml](../examples/github-workflow.yml).

DrRepo analyzes the public GitHub copy of the repository, not the CI checkout. Each SARIF result's `uri` is repo-relative, so GitHub annotates the right files.

## MCP server

`drrepo mcp` exposes DrRepo over the [Model Context Protocol](https://modelcontextprotocol.io), so an assistant can audit a repository and work through the findings itself.

### Client setup

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

**From Python:** [examples/mcp_client.py](../examples/mcp_client.py) starts the server over stdio, calls `analyze_repository` with progress notifications, and reads a report resource.

**Claude Code:**

```bash
claude mcp add drrepo -- uv --directory /absolute/path/to/DrRepo run drrepo mcp
```

**Remote / HTTP:** `drrepo mcp --transport streamable-http --host 0.0.0.0 --port 8765` serves at `http://host:8765/mcp` (also available through `docker compose --profile mcp up`). Put it behind your own auth before exposing it: the server has no authentication of its own, and every call can trigger a clone and LLM spend.

With stdio transport, stdout belongs to the protocol. All DrRepo logging goes to stderr and the log file.

### Tools

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

### Resources

| URI | MIME type |
|---|---|
| `drrepo://reports/{owner}/{name}` | `application/json` |
| `drrepo://reports/{owner}/{name}/markdown` | `text/markdown` |
| `drrepo://reports/{owner}/{name}/sarif` | `application/sarif+json` |

### Prompts

`review_repository(repo_url, focus="")` walks the assistant through four steps: analyze, pull high-severity issues, build a prioritized fix plan with file paths, and list quick wins.

### Notes

- One `AnalysisService` lives for the server process, so the LLM circuit breaker and dependency cache carry across tool calls.
- Progress notifications are best-effort. A client that doesn't support them never causes an analysis to fail.

## Troubleshooting

Start with `uv run drrepo doctor`. It checks Python, git, the scanners, imports, configuration, writable directories, and connectivity, and marks each item OK, WARN, or FAIL. `uv run drrepo health` checks only connectivity. Detailed logs are in `logs/app.log`; set `LOG_LEVEL=DEBUG` or pass `-v` for more.

| Symptom | Cause | Fix |
|---|---|---|
| `configuration error: X=... is not a boolean` | a malformed value in `.env` | use `true`/`false`; numbers must be plain integers |
| `warning: GROQ_API_KEY not set` | no LLM key | add it to `.env`. Without it, reports are deterministic only |
| `git clone failed (repository is private or does not exist)` | private repo, typo, or renamed repo | only public repositories are supported; check the URL |
| `Clone timed out` / `over the ...MB analysis limit` | very large repository | raise `CLONE_TIMEOUT_SECONDS` / `CLONE_MAX_SIZE_MB` |
| `GitHub API rate limit exceeded` | 60 requests/hour unauthenticated | set `GH_TOKEN` (no scopes needed). DrRepo falls back to the clone for the README and structure |
| a category shows `n/a` | its inputs were unavailable (see its summary): no Python code for ruff, OSV unreachable, no README source | expected; the category is excluded from the overall score |
| `semgrep: skipped: semgrep timed out` | slow first run (ruleset download) or huge repo | raise `COLLECTOR_TIMEOUT_SECONDS`, or `ENABLE_SEMGREP=false` |
| `semgrep not installed` on Windows | semgrep wheels may not support your platform | `ENABLE_SEMGREP=false`; bandit and the secret scanner still run |
| note: `LLM summary unavailable (CircuitOpenError)` | the provider failed repeatedly (quota or outage) and the breaker opened | wait `LLM_CIRCUIT_BREAKER_TIMEOUT_SECONDS`, or check `drrepo health`. The rest of the report is unaffected |
| note: `Deep investigation reached its N-tool-call budget` | the agent didn't conclude in time | raise `MAX_TOOL_CALLS_PER_INVESTIGATOR` / `INVESTIGATOR_TIMEOUT_SECONDS` |
| plan rationale says `downgraded ... token budget` | the per-run budget allows fewer deep dives than the planner wanted | raise `LLM_TOKEN_BUDGET_PER_RUN` or lower `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION` |
| Groq `413` / `tokens per day` | daily quota exhausted | wait for the reset, switch `MODEL_NAME`, or run `--shallow` |
| `attempted to call tool ' _Something'` | a pydantic output class name starts with `_` | rename it (see the planner section in [architecture.md](architecture.md)) |
| MCP client shows garbled output | something printed to stdout under the stdio transport | don't add `print()` to code paths used by `drrepo mcp`; log instead (logs go to stderr) |
| Streamlit stuck on "Analyzing…" | the worker thread died | the error is shown on the next rerun and in `logs/app.log` |
| `uv sync` fails behind a proxy | network | set `HTTPS_PROXY`; uv honors it |
| Docker: `failed to connect to the docker API` | the Docker daemon isn't running | start Docker Desktop / `dockerd` |

### Reporting a bug

Include the `drrepo doctor` output, the command you ran, and the relevant part of `logs/app.log`. Remove tokens before sharing.
