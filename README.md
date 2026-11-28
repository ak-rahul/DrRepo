# 🩺 DrRepo

[![CI](https://github.com/ak-rahul/DrRepo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ak-rahul/DrRepo/actions/workflows/ci.yml)
![Python 3.11–3.14](https://img.shields.io/badge/python-3.11%E2%80%933.14-blue)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)

**Agentic health check for public GitHub repositories.**

DrRepo clones a repository, runs real scanners over it (ruff, bandit, semgrep, a secret scanner, OSV.dev and deps.dev lookups), and gives the results to a *Lead Investigator* LLM agent. That agent decides which categories need a deep, tool-calling investigation. Everything ends up in one scored report: JSON, Markdown, SARIF for GitHub code scanning, or a CycloneDX SBOM.

Code from the analyzed repository is never executed, installed, or built.

| Category | Signals |
|---|---|
| Security | bandit, semgrep (security audit plus per-language rulesets), secret scanner (plus git history with `--scan-history N`), zizmor (CI workflows), hadolint (Dockerfiles), OpenSSF Scorecard |
| Code quality | ruff (bug-class rules), lizard complexity and function length, copy-paste detection; normalized per 1k lines |
| Dependencies | OSV.dev advisories for exact pins/lockfiles, license policy or compatibility, deprecated or long-unreleased packages (deps.dev), pinning, CycloneDX SBOM |
| Documentation | README structure and completeness |
| Maintainability | tests, CI, license, policies, activity, archived status |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and `git`.

```bash
git clone https://github.com/ak-rahul/DrRepo && cd DrRepo
uv tool install --editable .   # puts `drrepo` on your PATH (tracks this checkout)
cp .env.example .env           # optional: GROQ_API_KEY, GH_TOKEN (a .env.local next to it wins)
```

| Command | Does |
|---|---|
| `drrepo audit <url>` | audit a repository (`--ref R` for a branch, tag or SHA) |
| `drrepo quick <url>` | fast, deterministic audit (no LLM) |
| `drrepo diff <url> <base> [head]` | what a change made better or worse |
| `drrepo ui` | web UI on http://localhost:8501 |
| `drrepo doctor` | check the setup |

`drrepo <url>` is short for `drrepo audit <url>`, and `drrepo --help` lists every command. Without the tool install, prefix commands with `uv run` inside the checkout. semgrep is optional: `uv tool install semgrep` (the Docker image includes it).

Providers: Groq (default), OpenAI, Anthropic (`uv sync --extra anthropic`), or local models through Ollama (`uv sync --extra ollama`), with an optional model per role. Without an API key DrRepo still runs. The report is then fully deterministic, with no LLM summaries and no deep investigation.

## Interfaces

- **CLI**: `drrepo audit <url> [--format json,md,sarif,cdx,summary] [--fail-under 70]`, or `drrepo quick <url>` without LLM investigations. The exit code makes it usable as a CI gate. `drrepo diff <url> main <sha>` reports what a change made better or worse.
- **GitHub Action**: `uses: ak-rahul/DrRepo@<sha>` gates on the score or, on pull requests, on what the change made worse; uploads SARIF to code scanning; and keeps a summary comment on pull requests. See [docs/usage.md](docs/usage.md#in-ci-the-github-action).
- **Web UI**: audit a commit or compare two, with live progress, issue search and filters, one-click "mark as false positive" (writes a suppression), what the agent read for each of its findings, dependencies, suppressions, the tool-call trace and token use, a score trend, and every export.
- **Organizations**: `drrepo org <owner>` audits an organization's repositories and writes a leaderboard and one SARIF log. See [docs/usage.md](docs/usage.md#auditing-an-organization).
- **Python**: `AnalysisService(Config.from_env()).analyze(url)`. See [examples/](examples/).
- **REST API**: `drrepo serve` queues analyses as background jobs (API keys, per-key rate limits), serves score history, report exports and shields.io badges, plus health checks. Prometheus metrics at `/metrics`, JSON logs and optional OpenTelemetry traces. See [docs/usage.md](docs/usage.md#rest-api).

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
| [Usage](docs/usage.md) | CLI, UI, Python API, Docker, CI/SARIF, troubleshooting |
| [Configuration](docs/configuration.md) | every environment variable |
| [Architecture](docs/architecture.md) | design, pipeline, resilience, security model |
| [Agents](docs/agents.md) | every agent's job, tools, bounds, and how to edit its instructions |
| [Report format](docs/report-format.md) | JSON schema, scoring math, SARIF and CycloneDX mapping |
| [Development](docs/development.md) | setup, tests, extending DrRepo |
| [Changelog](CHANGELOG.md) · [Security](SECURITY.md) | release notes · reporting vulnerabilities |

## License

MIT. See [LICENSE.md](LICENSE.md).
