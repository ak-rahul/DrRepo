# Configuration

All settings come from environment variables, optionally loaded from `.env.local` (machine-specific, never committed) and `.env`; the first that sets a variable wins, and real environment variables beat both. `--env-file` names another file, and its `.local` sibling is read too. `Config.from_env()` is the only code that reads the environment. Invalid values (`ENABLE_SEMGREP=maybe`, `MAX_TOKENS=lots`, an unknown provider) fail at startup with a `ConfigurationError` that names the variable. Booleans accept `true/false/1/0/yes/no/on/off`. Values are also range-checked however `Config` is built (from the environment or in code): timeouts, limits and the breaker threshold must be at least 1, the token budget and breaker timeout must not be negative, `TEMPERATURE` must be 0–2, and `LOG_LEVEL` must be a standard level name. `Config` is immutable; derive variants with `dataclasses.replace`.

## LLM provider

| Variable | Default | Notes |
|---|---|---|
| `MODEL_PROVIDER` | `groq` | `groq`, `openai`, `anthropic` (extra `anthropic`), or `ollama` (extra `ollama`, local models: code never leaves the machine) |
| `MODEL_NAME` | provider default | groq `openai/gpt-oss-120b` (Groq retired `llama-3.3-70b-versatile`), openai `gpt-4o-mini`, anthropic `claude-sonnet-5-5`, ollama `llama3.1`. Must support tool calling for deep mode |
| `MODEL_NAME_PLANNER` | `MODEL_NAME` | model for the Lead Investigator and the documentation rubric (structured output) |
| `MODEL_NAME_NARRATIVE` | `MODEL_NAME` | model for the short category summaries (a small, cheap model is fine) |
| `MODEL_NAME_INVESTIGATION` | `MODEL_NAME` | model for deep tool-calling investigations (pick your most reliable tool-user) |
| `MODEL_NAME_CRITIC` | `MODEL_NAME` | model for the critic's second look at severe agent findings (a different model family makes it more independent) |
| `GROQ_API_KEY` | — | required when the provider is `groq` |
| `OPENAI_API_KEY` | — | required when the provider is `openai` |
| `ANTHROPIC_API_KEY` | — | required when the provider is `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server for the `ollama` provider (no key) |

All roles share one circuit breaker and one per-run token budget, so routing roles to different models can't hide an outage or double the spend. `drrepo health` checks that the provider offers every configured model. Optional providers are installed as extras: `uv sync --extra anthropic` or `uv sync --extra ollama` (`pip install "drrepo[anthropic]"` from a wheel).
| `TEMPERATURE` | `0.3` | |
| `MAX_TOKENS` | `2000` | max completion tokens per call |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | per HTTP request to the provider |

If the provider's key is missing, DrRepo runs without an LLM: findings and scores are produced as usual, summaries come from templates, and the plan is all-shallow.

## GitHub

| Variable | Default | Notes |
|---|---|---|
| `GH_TOKEN` (or `GITHUB_TOKEN`) | — | optional. Raises the API limit from 60 to 5000 requests/hour. A token with no scopes is enough for public repositories |

## Clone and collectors

| Variable | Default | Notes |
|---|---|---|
| `CLONE_TIMEOUT_SECONDS` | `60` | |
| `CLONE_MAX_SIZE_MB` | `300` | larger clones are deleted and clone-based collectors are skipped |
| `COLLECTOR_TIMEOUT_SECONDS` | `120` | per scanner subprocess and HTTP client |
| `ENABLE_SEMGREP` | `true` | semgrep is the slowest scanner and downloads its ruleset. It runs only if installed (`uv tool install semgrep`) |
| `ENABLE_BANDIT` | `true` | |
| `ENABLE_DEPENDENCY_AUDIT` | `true` | OSV.dev lookups |
| `ENABLE_LICENSE_AUDIT` | `true` | deps.dev license lookups (runtime dependencies only, max 30) |
| `ENABLE_MAINTENANCE_AUDIT` | `true` | deps.dev deprecation flags and newest release dates (runtime dependencies only, max 30): deprecated packages, and packages with no release in two years |
| `ENABLE_COMPLEXITY_METRICS` | `true` | lizard cyclomatic complexity and function length, and copy-paste detection, over product code in 20 languages (tests, examples, docs and vendored code excluded) |
| `SCAN_HISTORY_COMMITS` | `0` | opt-in: also scan the lines the last N commits added for secrets (`--scan-history N`). The clone then fetches N+1 commits, which counts toward `CLONE_MAX_SIZE_MB`; at most 1000 |
| `LICENSE_DENY` | empty | comma-separated SPDX ids (case-insensitive). A runtime dependency under one is a high `license-denied` issue |
| `LICENSE_ALLOW` | empty | comma-separated SPDX ids. A runtime dependency under any other known license is a medium `license-not-allowed` issue |
| `ENABLE_WORKFLOW_AUDIT` | `true` | zizmor over the repository's GitHub Actions workflows (offline) |
| `ENABLE_DOCKERFILE_AUDIT` | `true` | hadolint plus a root-user check over the repository's Dockerfiles |
| `ENABLE_SCORECARD` | `true` | OpenSSF Scorecard lookup (public API; repositories without a published Scorecard are skipped) |

Setting either license variable replaces the built-in heuristic (copyleft dependencies in a permissively licensed repository). Dependencies with no license metadata are not policy violations; compound expressions such as `MIT OR Apache-2.0` are matched as written.

## Agentic investigation

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_DEEP_INVESTIGATION` | `true` | `false` = every category shallow (the CLI equivalent is `--shallow`) |
| `ENABLE_LLM_JUDGMENT` | `true` | bounded LLM judgment that can adjust a score: the documentation rubric, at most ±25 points. `false` = README metrics only |
| `ENABLE_MCP_TOOLS` | `true` | investigators call their tools through DrRepo's in-memory MCP tool server; `false` calls the same tools in-process |
| `ENABLE_AGENT_CRITIC` | `true` | re-check grounded high/critical agent findings; the critic can lower a severity or mark a finding disputed, never raise or remove one |
| `MAX_TOOL_CALLS_PER_INVESTIGATOR` | `8` | step budget per investigation |
| `INVESTIGATOR_TIMEOUT_SECONDS` | `90` | wall-clock budget per investigation |

## Resilience and cost

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_LLM_CIRCUIT_BREAKER` | `true` | shared across parallel nodes and across runs in one process |
| `LLM_CIRCUIT_BREAKER_THRESHOLD` | `3` | consecutive failed logical calls before opening |
| `LLM_CIRCUIT_BREAKER_TIMEOUT_SECONDS` | `300` | open time before one probe call is allowed |
| `ENABLE_LLM_BUDGET_TRACKING` | `true` | |
| `LLM_TOKEN_BUDGET_PER_RUN` | `60000` | reset at the start of every run |
| `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION` | `12000` | expected cost of one deep investigation (a lite one costs half) until score history has measurements; measured estimates stay within ¼× and 4× of this |
| `ENABLE_DEPENDENCY_LOOKUP_CACHE` | `true` | in-memory, per process |
| `ENABLE_SCORE_HISTORY` | `true` | appends to `reports/history.json` (20 runs per repository) |
| `SUPPRESSIONS_FILE` | empty | suppression file (`.drrepo.toml` format) applied to every analysis |
| `TRUST_REPO_SUPPRESSIONS` | `false` | also honor the analyzed repository's own `.drrepo.toml`. Enable only for your own repositories: otherwise a repository could hide its own findings |

## Logging

| Variable | Default | Notes |
|---|---|---|
| `LOG_LEVEL` | `INFO` | applies to the log file (`logs/app.log`, override with `--log-file`; `--log-file ''` disables it). The CLI console shows only warnings unless `-v` is passed |

## Tuning recipes

- **Fast and cheap:** `ENABLE_DEEP_INVESTIGATION=false ENABLE_SEMGREP=false` gives a typical run in under 30 seconds.
- **Free-tier Groq:** keep the defaults. On a provider 429/413 error the breaker opens after 3 failures, and the rest of the run finishes deterministically.
- **Thorough:** raise `LLM_TOKEN_BUDGET_PER_RUN` to `150000` and `MAX_TOOL_CALLS_PER_INVESTIGATOR` to `15`.
