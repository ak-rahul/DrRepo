# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- semgrep is no longer a project dependency. It hard-pinned `mcp`, `opentelemetry-api` and `wcmatch` to versions with known CVEs. Install it as an isolated tool with `uv tool install semgrep`; the Docker image includes it.
- Added `.dockerignore`, so `.env` files and the local virtualenv never enter the Docker build context.

### Changed
- Upgraded to MCP Python SDK 2 (`MCPServer`). A missing report is now a tool error (`is_error`) for tools and JSON-RPC "not found" for resources. Host and port are passed to the transport directly.
- Upgraded FastAPI to 0.165 and refreshed `uv.lock`.

### Fixed
- MCP progress notifications sent from LangGraph's worker threads were silently dropped. Clients now receive every step.
- The CI audit job combined `--no-hashes` with `--disable-pip`, a pairing pip-audit rejects. It now audits a hashed export.
- Coverage now includes the Streamlit app. It used to report 0% because the app runs as `__main__`.

### Added
- Examples: `policy_gate.py`, `custom_collector.py`, `mcp_client.py`, `github-workflow.yml` and an examples index. All examples are linted, type-checked, and tested.
- Dependabot for uv, GitHub Actions and Docker. The CI Docker job now smoke-tests the built image.
- `SECURITY.md` and this changelog.

## [3.1.0] - 2026-11-27

### Changed
- Restructured into a `src/drrepo` package (`recon/`, `agents/`, `interfaces/`), with uv as the only package manager.
- The analysis graph is compiled once per process. Per-run state (config, token budget, cache, progress) lives in a `RunContext`, so concurrent runs are safe.
- Short README; detailed documentation moved to `docs/`.

### Added
- MCP server (`drrepo mcp`): 8 tools, 3 report resources, and 1 prompt.
- `drrepo doctor` diagnostics and `--fail-under` CI gating.

### Fixed
- Every category ran twice because of a LangGraph fan-in deferral bug.
- Dev-only dependency advisories and test-fixture secrets no longer dominate scores.

## [3.0.0] - 2026-07-05

### Added
- Agentic investigation layer: a Lead Investigator plans deep, tool-calling investigations per category.
- License checks and SARIF export.
- Resilience layer: LLM circuit breaker, per-run token budget, dependency lookup cache, and score history.

## [2.0.0] - 2026-07-04

### Changed
- Rewritten as a code-analysis platform built on real scanners.

## [1.0.0]

- Initial release.
