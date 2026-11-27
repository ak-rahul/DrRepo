# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- `search_code` (an investigator tool whose regex the LLM chooses) could be stalled forever by a catastrophic-backtracking pattern, for example one planted by prompt injection in an analyzed repository. Matching now uses `regex` with a per-line timeout and a total time budget.
- Four README patterns were quadratic in attacker-controlled input (7 s for 30k newlines). They are now linear, and README text is capped at 100k characters everywhere, including the GitHub API path and the MCP `analyze_readme_text` tool.
- `docker-compose.yml` publishes ports on `127.0.0.1` only. Previously the unauthenticated UI, health API and MCP server were reachable from the network.
- GitHub Actions are pinned to commit SHAs, and checkout no longer persists credentials.
- The image no longer contains curl, and app code is read-only to the app user. The sdist is an allow-list, so local files never ship.
- semgrep is no longer a project dependency. It hard-pinned `mcp`, `opentelemetry-api` and `wcmatch` to versions with known CVEs. Install it as an isolated tool with `uv tool install semgrep`; the Docker image includes it.
- Added `.dockerignore`, so `.env` files and the local virtualenv never enter the Docker build context.

### Changed
- `reporting.py` and `exporters.py` became the `report/` package: `synthesis` (pure), `history` (disk) and `exporters`. Tests mirror it in `tests/report/`.
- `Config` is frozen and validated on construction (ranges, provider, log level), so a bad value fails at startup with the variable's name instead of deep inside a run.
- mypy runs in strict mode. More ruff rule families: PIE, PERF, FURB, LOG, DTZ, PTH and PLW.
- Report file timestamps are UTC (`..._20261127-091500Z.json`).
- Upgraded to MCP Python SDK 2 (`MCPServer`). A missing report is now a tool error (`is_error`) for tools and JSON-RPC "not found" for resources. Host and port are passed to the transport directly.
- Upgraded FastAPI to 0.165 and refreshed `uv.lock`.

### Fixed
- The README was read from the GitHub API, which always serves HEAD, even when a specific commit was analyzed. It now comes from the clone, falling back to the API.
- Score history: a failed write (read-only volume, a file locked on Windows) no longer fails a finished analysis. Concurrent writers from separate processes (UI and MCP server sharing `reports/`) no longer lose updates.
- MCP progress notifications sent from LangGraph's worker threads were silently dropped. Clients now receive every step.
- The CI audit job combined `--no-hashes` with `--disable-pip`, a pairing pip-audit rejects. It now audits a hashed export.
- Coverage now includes the Streamlit app. It used to report 0% because the app runs as `__main__`.

### Added
- Suppressions and baselines: a `.drrepo.toml` with `[[suppress]]` entries (rule, optional path glob, required reason, optional expiry) excludes reviewed findings from scores while keeping them visible in the report and as native SARIF suppressions. `drrepo baseline` writes one from the current findings. A repository's own file applies only with `TRUST_REPO_SUPPRESSIONS`.
- CI workflow and container security for analyzed repositories, in a new `infrastructure` collector:
  - zizmor audits GitHub Actions workflows and Dependabot config, catching template injection, dangerous triggers, unpinned actions and broad tokens.
  - hadolint lints Dockerfiles.
  - A built-in check flags containers that never drop root.
  - The repository's own configuration and ignore comments can't silence these findings.
  - They count toward security on a bounded curve, at most 40%. Toggles: `ENABLE_WORKFLOW_AUDIT`, `ENABLE_DOCKERFILE_AUDIT`.
- `drrepo eval`: an evaluation set of pinned public repositories (`evals/`) compared with a recorded baseline. It reports per-category score drift, findings that appear or disappear, agent precision from human labels, tool calls, tokens and time. It exits 3 on a regression, and runs in CI's integration job.
- Grounding check for agent findings: every investigator issue is verified against the clone and the agent's own tool trace. Findings citing missing files or lines are dropped, and findings the agent never examined are capped at low and marked `[unverified]`. Agents can quote an `evidence` excerpt, which is checked against the cited file.
- Commit pinning: `--ref` (CLI), `ref` (MCP, Python API, web UI) analyzes a branch, tag, or full commit SHA. Every report records `repository.commit_sha` and `ref`, SARIF output carries `versionControlProvenance`, and score history notes which commit each run saw.
- Agent instructions as documents: every agent's prompt is a markdown file in `agents/instructions/`, loaded at runtime and validated in tests, `drrepo doctor` and CI. They add severity calibration, an evidence standard, per-category checklists and a prompt-injection guard. New guide: `docs/agents.md`.
- End-to-end tests of the LLM paths: the real LangChain agent loop, real tools on a temporary clone, and the real planner, driven by a scripted tool-calling model (no API key needed).
- Python 3.14 support (CI matrix and classifiers); `py.typed` marker.
- CI: package job (build, `twine check`, clean-venv wheel install), workflow security and syntax linting (zizmor, actionlint), hadolint, job timeouts.
- pre-commit: zizmor, actionlint, hadolint, and schema validation for workflows, Dependabot and the compose file.
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
