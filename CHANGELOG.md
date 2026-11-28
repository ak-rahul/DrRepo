# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- Investigation notes no longer quote the LLM provider's raw error, which can include account or organization ids. They give the HTTP status and a short reason, and the full error stays in the log.
- `Config` no longer shows API keys or tokens in its `repr`.
- The web UI rendered text from the analyzed repository (issue titles and descriptions, summaries, notes, file names) as Markdown, so a planted `![](https://...)` could load a remote image (a tracking pixel) and `$...$` rendered as LaTeX. All such text is now escaped (`interfaces/ui_data.escape_markdown`); tables and code blocks show it as plain text.
- `search_code` (an investigator tool whose regex the LLM chooses) could be stalled forever by a catastrophic-backtracking pattern, for example one planted by prompt injection in an analyzed repository. Matching now uses `regex` with a per-line timeout and a total time budget.
- Four README patterns were quadratic in attacker-controlled input (7 s for 30k newlines). They are now linear, and README text is capped at 100k characters everywhere, including the GitHub API path.
- `docker-compose.yml` publishes ports on `127.0.0.1` only. Previously the unauthenticated UI and health API were reachable from the network.
- GitHub Actions are pinned to commit SHAs, and checkout no longer persists credentials.
- The image no longer contains curl, and app code is read-only to the app user. The sdist is an allow-list, so local files never ship.
- semgrep is no longer a project dependency. It hard-pinned `mcp`, `opentelemetry-api` and `wcmatch` to versions with known CVEs. Install it as an isolated tool with `uv tool install semgrep`; the Docker image includes it.
- Added `.dockerignore`, so `.env` files and the local virtualenv never enter the Docker build context.

### Changed
- `reporting.py` and `exporters.py` became the `report/` package: `synthesis` (pure), `history` (disk) and `exporters`. Tests mirror it in `tests/report/`.
- `Config` is frozen and validated on construction (ranges, provider, log level), so a bad value fails at startup with the variable's name instead of deep inside a run.
- mypy runs in strict mode. More ruff rule families: PIE, PERF, FURB, LOG, DTZ, PTH and PLW.
- Report file timestamps are UTC (`..._20261127-091500Z.json`).
- Upgraded FastAPI to 0.165 and refreshed `uv.lock`.

### Fixed
- The default Groq model is now `openai/gpt-oss-120b`: Groq retired `llama-3.3-70b-versatile`, so every LLM call failed with `NotFoundError`.
- Deep investigations failed on models with native structured output ("json mode cannot be combined with tool/function calling"). Findings are now always submitted as a tool call (`ToolStrategy`), and each model call in the agent loop retries rate limits and 5xx like every other LLM call.
- An unexpected exception inside any collector crashed the whole analysis. The collector node now turns it into an `error` result, and the run continues.
- The documentation narrative excerpt also came from the HEAD README instead of the analyzed commit.
- The README was read from the GitHub API, which always serves HEAD, even when a specific commit was analyzed. It now comes from the clone, falling back to the API.
- Score history: a failed write (read-only volume, a file locked on Windows) no longer fails a finished analysis. Concurrent writers from separate processes (the UI and a CLI run sharing `reports/`) no longer lose updates.
- The CI audit job combined `--no-hashes` with `--disable-pip`, a pairing pip-audit rejects. It now audits a hashed export.
- Coverage now includes the Streamlit app. It used to report 0% because the app runs as `__main__`.

### Removed
- `drrepo.interfaces.health.app`: the health endpoints are now a router inside the REST API (`drrepo serve`).
- The external MCP server (`drrepo mcp`, its Docker Compose profile and the MCP client examples). MCP is now used only inside DrRepo: each investigator calls its tools through the in-memory tool server. Assistants can run the CLI (`drrepo audit --json`) instead.

### Added
- `drrepo label`: walks through the unlabeled agent findings of the last `drrepo eval` run (now saved to `reports/eval/`), with a link to the cited line at the analyzed commit and the agent's evidence, and records your verdicts in `evals/labels.toml`.
- HTML report (`--format html`): a self-contained page with no scripts and light and dark themes, also in the web UI's downloads and the API. Repository text is escaped by the template engine and the page carries a strict Content-Security-Policy.
- Organization batch mode: `drrepo org <owner>` audits an organization's (or user's) newest-pushed public repositories on a bounded pool, and writes a Markdown/JSON leaderboard with each repository's change since the previous run, plus one SARIF log with a run per repository.
- `LOG_FORMAT=json`: one JSON object per log line.
- Clone cache by commit (`CLONE_CACHE_TTL_SECONDS`, off by default): `git ls-remote` resolves the commit, and a cached clone of it is copied out instead of cloning again.
- Scanner resource limits: on Linux, scanners and `git log` run under `prlimit` (a file-size cap by default, an opt-in memory cap).
- Web UI: "mark as false positive" on every issue appends a suppression with your reason and an expiry, and each agent finding shows the tool calls that read the cited file.
- Local API: `drrepo serve` replaces `drrepo health-api` (still accepted as an alias) and keeps its health endpoints. `POST /analyses` queues an analysis as a background job on a bounded worker pool; `GET /analyses/{id}` reports status and progress, `/analyses/{id}/report?format=` exports it, and `/repos/{owner}/{name}/history` and `/report` serve history. It serves this machine only: remote callers and requests with proxy headers get 403.
- Persistent store: `STORE_BACKEND=sqlite` keeps scores, full reports and API jobs in `reports/drrepo.db` (WAL mode, safe across processes), so queued jobs resume after a restart. The JSON history stays the default. `AnalysisService(store=...)` replaces `history_path=`.
- Investigations fit small rate limits. Each investigator sees only its own collectors' data, as compact JSON without the README: first requests dropped from about 7,200 tokens to 2,000-3,700. `INVESTIGATION_CONTEXT_TOKENS` caps a whole request by clearing older tool results and cutting long ones, `LLM_MAX_PARALLEL_INVESTIGATIONS` runs investigations one at a time, and each model call in the agent loop waits out the provider's `retry-after` within the time budget. A malformed tool call the model generated (Groq `tool_use_failed`) is now retried instead of failing the call, and a daily quota fails at once instead of being retried.
- An investigation that uses up its tool calls now submits what it found: further tool calls are answered "budget used up" without running. Before, it ended with a `GraphRecursionError` and its findings were lost.
- Complexity and duplication metrics (`recon/complexity.py`): lizard cyclomatic complexity and function length in 20 languages, and a copy-paste detector, over product code only. They feed Code Quality as aggregated issues (`high-complexity`, `very-high-complexity`, `long-function`, `duplicated-code`), so repositories without Python now get a Code Quality score. Toggle: `ENABLE_COMPLEXITY_METRICS`.
- Abandoned dependencies: deps.dev deprecation flags (`deprecated-package`, medium) and newest release dates (`stale-package`, one low issue for runtime packages with no release in two years). Toggle: `ENABLE_MAINTENANCE_AUDIT`.
- Opt-in secret history scan: `--scan-history N` (`SCAN_HISTORY_COMMITS`) clones N+1 commits and runs the secret patterns over the lines each commit added, reporting secrets the current tree no longer has with the commit that added them.
- Investigators call their tools over MCP: each investigation starts DrRepo's own MCP tool server (`agents/tool_server.py`) for the clone, connected in memory, exposing only that category's read-only tools; the agent chooses among them by their descriptions. A failed call is an `ERROR:` result for the agent; a server that can't start falls back to in-process tools with a note. The server is internal to the agents. Toggle: `ENABLE_MCP_TOOLS`.
- Short commands: `drrepo audit <url>` (`analyze` stays as an alias), `drrepo quick <url>` for a deterministic audit, `drrepo diff <url> <base> [head]` with positional refs, and `uv tool install --editable .` to put `drrepo` on PATH. Development shortcuts: `uv run poe test|lint|fmt|types|fix|check`. `.env.local` is loaded automatically and wins over `.env`.
- Web UI: compare mode (base vs. head, with new, worse and fixed issues and the head report), recent analyses that survive a page refresh, a score-over-time chart, Dependencies, Suppressed and Details (models, scanner versions, instruction hashes) tabs, token usage per step, distinct deep and lite markers, issue search and source/origin filters with paging, and the summary download. View logic lives in `interfaces/ui_data.py` and is unit-tested.
- Code-symbol index for investigators: a `symbols` tool family (`find_definition`, `find_references`, `outline`) for the security and code-quality agents, backed by a per-run, in-memory index shared across categories. Python uses `ast` (exact); JS/TS, Go, Java/Kotlin/C#, Ruby, Rust and PHP use conservative line patterns. No new dependency.
- Documentation checks (`doc_checks` collector): broken internal links and anchors in the README and `docs/`, documented `npm`/`yarn`/`pnpm`/`make` commands and project commands that don't exist, and docstring coverage of public Python APIs. They count against the documentation score by at most 15 points.
- Pull-request diff mode: `drrepo diff <url> <base> [head]` analyzes both commits and reports new, worsened and fixed issues with per-category score deltas, ignoring line moves. `--deep` investigates the head with tools only in categories that got worse. Gates: `--fail-on-new SEVERITY`, `--max-score-drop N`, `--fail-under`. Also `AnalysisService.compare()`, the action's `mode: diff` (with `base` and `fail-on-new`), and a versioned contract, `diff.schema.json`.
- Critic for severe agent findings: after grounding, an investigation's high and critical findings get an independent, tool-free second look (`agents/instructions/critic.md`, its own model role `MODEL_NAME_CRITIC` and budget line). It can confirm, lower a finding one level, or dispute it (low, marked `[disputed]`, still listed); it can never raise a severity, remove a finding or touch scanner output. `drrepo eval` reports its agreement with labeled false positives. Toggle: `ENABLE_AGENT_CRITIC`.
- Adaptive budgets: the planner can choose a `lite` investigation (half the tool calls, half the cost) for borderline categories, and plans in budget units (deep 2, lite 1), demoting deep to lite before shallow. Token usage is recorded per step (`llm_usage.by_label`), score history keeps what each investigation really cost, and the next run sizes its plan from those measurements (`llm_usage.deep_estimate`), within ¼× and 4× of `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION`.
- GitHub Action (`action.yml`): `uses: ak-rahul/DrRepo@<sha>` analyzes the pushed commit or pull request head with the DrRepo code at the pinned ref, gates on `fail-under`, uploads SARIF, writes a job summary, and can keep one summary comment on the pull request. Outputs: `score`, `grade`, `report`, `sarif`. CI runs it on a pinned repository, and pre-commit lints it with zizmor and its schema.
- `--format summary`: a short Markdown summary (score, categories, top issues) for PR comments and job summaries. Text from the analyzed repository is neutralized, so it can't mention people or load images.
- Dependency depth:
  - Every report lists its `dependencies` (ecosystem, name, version, runtime or dev scope, license, advisory ids).
  - `--format cdx` exports them as a CycloneDX 1.6 SBOM with package URLs and OSV vulnerabilities.
  - `LICENSE_DENY` and `LICENSE_ALLOW` enforce an explicit license policy in place of the copyleft heuristic.
  - Vulnerable runtime packages note how many source files import them directly. A package that is never imported directly is marked as likely transitive; its severity doesn't change, because it is still reachable through its parent.
- Language-aware semgrep: registry rulesets for the repository's main languages (up to 3) run alongside `p/security-audit`. The report records which ran.
- OpenSSF Scorecard: checks a shallow clone can't see (branch protection, code review, signed releases, binary artifacts, fuzzing, SAST) count toward security on the bounded curve. Checks overlapping DrRepo's own are skipped, and a scan of a different commit is noted. Toggle: `ENABLE_SCORECARD`.
- Model routing and providers: optional `MODEL_NAME_PLANNER`, `MODEL_NAME_NARRATIVE` and `MODEL_NAME_INVESTIGATION` choose a model per role (sharing one breaker and budget), and the providers `anthropic` and `ollama` (local; code never leaves the machine) ship as optional extras. `MODEL_NAME` now defaults per provider, `drrepo health` checks every configured model, and provenance records the model per role.
- Documentation rubric: with an LLM available, the README is graded against six criteria using the project's real build config as ground truth. Code turns the verdicts into points and moves the documentation score by at most ±25, so a prompt-injected README can't award itself a perfect score. Verdicts citing missing files are downgraded, and heading-based false positives are downgraded, never removed. Toggle: `ENABLE_LLM_JUDGMENT`. The layout collector now reports `build_config` (package names, entry points, lockfiles).
- Provenance in every report: a hash of each agent instructions file as sent, the provider and model, and each scanner's version. It is also written to the SARIF run properties. `drrepo eval` lists provenance changes since the baseline, treats collector failures (for example GitHub rate limits) as environment problems, and won't baseline a degraded run.
- A versioned report contract: `schema_version` in every report, plus a JSON Schema (`drrepo/report/report.schema.json`) that ships in the package. Tests validate every report shape against it.
- Suppressions and baselines: a `.drrepo.toml` with `[[suppress]]` entries (rule, optional path glob, required reason, optional expiry) excludes reviewed findings from scores while keeping them visible in the report and as native SARIF suppressions. `drrepo baseline` writes one from the current findings. A repository's own file applies only with `TRUST_REPO_SUPPRESSIONS`.
- CI workflow and container security for analyzed repositories, in a new `infrastructure` collector:
  - zizmor audits GitHub Actions workflows and Dependabot config, catching template injection, dangerous triggers, unpinned actions and broad tokens.
  - hadolint lints Dockerfiles.
  - A built-in check flags containers that never drop root.
  - The repository's own configuration and ignore comments can't silence these findings.
  - They count toward security on a bounded curve, at most 40%. Toggles: `ENABLE_WORKFLOW_AUDIT`, `ENABLE_DOCKERFILE_AUDIT`.
- `drrepo eval`: an evaluation set of pinned public repositories (`evals/`) compared with a recorded baseline. It reports per-category score drift, findings that appear or disappear, agent precision from human labels, tool calls, tokens and time. It exits 3 on a regression, and runs in CI's integration job.
- Grounding check for agent findings: every investigator issue is verified against the clone and the agent's own tool trace. Findings citing missing files or lines are dropped, and findings the agent never examined are capped at low and marked `[unverified]`. Agents can quote an `evidence` excerpt, which is checked against the cited file.
- Commit pinning: `--ref` (CLI), `ref` (Python API, web UI) analyzes a branch, tag, or full commit SHA. Every report records `repository.commit_sha` and `ref`, SARIF output carries `versionControlProvenance`, and score history notes which commit each run saw.
- Agent instructions as documents: every agent's prompt is a markdown file in `agents/instructions/`, loaded at runtime and validated in tests, `drrepo doctor` and CI. They add severity calibration, an evidence standard, per-category checklists and a prompt-injection guard. New guide: `docs/agents.md`.
- End-to-end tests of the LLM paths: the real LangChain agent loop, real tools on a temporary clone, and the real planner, driven by a scripted tool-calling model (no API key needed).
- Python 3.14 support (CI matrix and classifiers); `py.typed` marker.
- CI: package job (build, `twine check`, clean-venv wheel install), workflow security and syntax linting (zizmor, actionlint), hadolint, job timeouts.
- pre-commit: zizmor, actionlint, hadolint, and schema validation for workflows, Dependabot and the compose file.
- Examples: `policy_gate.py`, `custom_collector.py`, `github-workflow.yml` and an examples index. All examples are linted, type-checked, and tested.
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
