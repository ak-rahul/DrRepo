# Configuration

All settings come from environment variables, optionally loaded from a `.env` file (`--env-file` changes which file is read). `Config.from_env()` is the only code that reads the environment. Invalid values (`ENABLE_SEMGREP=maybe`, `MAX_TOKENS=lots`, an unknown provider) fail at startup with a `ConfigurationError` that names the variable. Booleans accept `true/false/1/0/yes/no/on/off`. Values are also range-checked however `Config` is built (from the environment or in code): timeouts, limits and the breaker threshold must be at least 1, the token budget and breaker timeout must not be negative, `TEMPERATURE` must be 0–2, and `LOG_LEVEL` must be a standard level name. `Config` is immutable; derive variants with `dataclasses.replace`.

## LLM provider

| Variable | Default | Notes |
|---|---|---|
| `MODEL_PROVIDER` | `groq` | `groq` or `openai` |
| `MODEL_NAME` | `llama-3.3-70b-versatile` | must support tool calling for deep mode |
| `GROQ_API_KEY` | — | required when the provider is `groq` |
| `OPENAI_API_KEY` | — | required when the provider is `openai` |
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
| `ENABLE_WORKFLOW_AUDIT` | `true` | zizmor over the repository's GitHub Actions workflows (offline) |
| `ENABLE_DOCKERFILE_AUDIT` | `true` | hadolint plus a root-user check over the repository's Dockerfiles |

## Agentic investigation

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_DEEP_INVESTIGATION` | `true` | `false` = every category shallow (the CLI equivalent is `--shallow`) |
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
| `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION` | `12000` | the planner may choose at most `budget // estimate` deep categories |
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
