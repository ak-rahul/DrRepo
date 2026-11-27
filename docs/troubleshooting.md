# Troubleshooting

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
| `attempted to call tool ' _Something'` | a pydantic output class name starts with `_` | rename it (see the planner gotcha in architecture.md) |
| MCP client shows garbled output | something printed to stdout under the stdio transport | don't add `print()` to code paths used by `drrepo mcp`; log instead (logs go to stderr) |
| Streamlit stuck on "Analyzing…" | the worker thread died | the error is shown on the next rerun and in `logs/app.log` |
| `uv sync` fails behind a proxy | network | set `HTTPS_PROXY`; uv honors it |
| Docker: `failed to connect to the docker API` | the Docker daemon isn't running | start Docker Desktop / `dockerd` |

## Reporting a bug

Include the `drrepo doctor` output, the command you ran, and the relevant part of `logs/app.log`. Remove tokens before sharing.
