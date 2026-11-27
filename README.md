# 🩺 DrRepo

**Agentic health check for public GitHub repositories.**

DrRepo clones a repository, runs real scanners over it (ruff, bandit, semgrep, a secret scanner, OSV.dev and deps.dev lookups), and gives the results to a *Lead Investigator* LLM agent. That agent decides which categories need a deep, tool-calling investigation. Everything ends up in one scored report: JSON, Markdown, or SARIF for GitHub code scanning.

Code from the analyzed repository is never executed, installed, or built.

| Category | Signals |
|---|---|
| Security | bandit, semgrep `p/security-audit`, secret scanner |
| Code quality | ruff (bug-class rules), normalized per 1k lines |
| Dependencies | OSV.dev advisories for exact pins/lockfiles, license compatibility, pinning |
| Documentation | README structure and completeness |
| Maintainability | tests, CI, license, policies, activity, archived status |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and `git`.

```bash
git clone https://github.com/ak-rahul/DrRepo && cd DrRepo
uv sync
uv tool install semgrep     # optional extra scanner (Linux/macOS; included in the Docker image)
cp .env.example .env        # add GROQ_API_KEY (optional: GH_TOKEN)

uv run drrepo https://github.com/pallets/itsdangerous     # CLI
uv run drrepo ui                                          # web UI on :8501
uv run drrepo mcp                                         # MCP server (stdio)
```

Without an API key DrRepo still runs. The report is then fully deterministic, with no LLM summaries and no deep investigation.

## Interfaces

- **CLI**: `drrepo analyze <url> [--shallow] [--format json,md,sarif] [--fail-under 70]`. The exit code makes it usable as a CI gate.
- **Web UI**: live progress, issue filters, the investigator's tool-call trace, and report downloads.
- **MCP server**: 8 tools, 3 resources, and 1 prompt for Claude Desktop, Claude Code, and other MCP clients. See [docs/usage.md](docs/usage.md#mcp-server).
- **Python**: `AnalysisService(Config.from_env()).analyze(url)`. See [examples/](examples/).
- **Health API**: `drrepo health-api` serves liveness, readiness, and dependency checks.

## How it works

```
clone ─┬─ repo layout ──┐
       ├─ GitHub API ───┴─ README ─┐
       ├─ ruff ────────────────────┤
       ├─ bandit/semgrep/secrets ──┼─► Lead Investigator ─► 5 category nodes ─► report
       └─ OSV.dev / deps.dev ──────┘   (plans deep vs.      (deterministic findings
                                        shallow per budget)  + optional ReAct agent)
```

Findings and scores come from deterministic code; the LLM only writes summaries and adds evidence it verified with tools. If the LLM or any single scanner fails, that part of the report degrades and the rest of the run finishes. Details are in [docs/architecture.md](docs/architecture.md).

## Documentation

| | |
|---|---|
| [Usage](docs/usage.md) | CLI, UI, Python API, Docker, CI/SARIF, MCP server, troubleshooting |
| [Configuration](docs/configuration.md) | every environment variable |
| [Architecture](docs/architecture.md) | design, pipeline, agents, resilience, security model |
| [Report format](docs/report-format.md) | JSON schema, scoring math, SARIF mapping |
| [Development](docs/development.md) | setup, tests, extending DrRepo |
| [Changelog](CHANGELOG.md) · [Security](SECURITY.md) | release notes · reporting vulnerabilities |

## License

MIT. See [LICENSE.md](LICENSE.md).
