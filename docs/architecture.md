# Architecture

DrRepo runs one LangGraph workflow per analysis. Recon collectors gather facts, a planner agent decides where to look harder, five category nodes each run shallow or deep, and a synthesizer builds the report. Every interface (CLI, Streamlit, MCP) goes through one `AnalysisService`.

```
AnalysisService (one per process)
 ├─ Workflow            compiled once, stateless, shared by all runs
 ├─ chat model client   ┐
 ├─ CircuitBreaker      ├─ shared across runs
 ├─ DependencyLookupCache┘
 └─ analyze(url) ─► RunContext(config, LLMRuntime with fresh TokenBudget, cache, progress)
                     │
                     ▼  Workflow.run: clone (try/finally cleanup) ─► graph.invoke(state, context=ctx)

  START ─┬─ repo_layout ─────┐
         ├─ github_metadata ─┴─► readme ─┐
         ├─ static_analysis ─────────────┤
         ├─ security ────────────────────┼─► planner ─┬─► documentation_review ──┐
         └─ dependency_audit ────────────┘            ├─► code_quality_review ───┤
                                                      ├─► security_review ───────┼─► synthesizer ─► END
                                                      ├─► dependencies_review ───┤
                                                      └─► maintainability_review ┘
```

## Package layout

```
src/drrepo/
  config.py         Config (frozen, validated); from_env() is the only os.environ reader
  errors.py         DrRepoError, ConfigurationError, CircuitOpenError, InvestigationError
  log.py            logger + configure_logging (no import-time side effects)
  models.py         RepoRef, Issue, CategoryFinding, InvestigationPlan, Report, ...
  resilience.py     CircuitBreaker, retry_with_backoff, is_retryable_llm_error
  pipeline.py       RunContext, COLLECTORS registry, Workflow (the LangGraph graph)
  service.py        AnalysisService, save_report
  recon/            deterministic evidence: clone, files (fs helpers + layout), github,
                    readme, scanners (ruff/bandit/semgrep + 2 collectors), secrets,
                    manifests, dependencies (OSV/deps.dev + lookup cache)
  agents/           llm (chat model, TokenBudget, LLMRuntime), planner, investigator,
                    tools (all investigator tools + build_tools), analysts/ (one per category),
                    prompts (loader) + instructions/*.md (every agent's job, as documents)
  report/           synthesis (pure scoring), history (disk, locked), exporters (JSON/MD/SARIF)
  interfaces/       cli, streamlit_app, mcp_server, health (checks + FastAPI app)
```

Package `__init__.py` files contain only a docstring (`agents/analysts/__init__.py` also has `default_analysts()`). Import from the submodule you need, so importing `drrepo.models` doesn't load LangChain or Streamlit.

## Key design decisions

1. **Compiled once, run many times.** `Workflow` holds no per-run state. Everything run-specific travels in a `RunContext` through LangGraph's runtime context (`StateGraph(State, context_schema=RunContext)`; nodes receive `runtime.context`): the config (with per-run overrides), an `LLMRuntime` with a fresh `TokenBudget`, the dependency cache, and the progress callback. One compiled graph therefore serves concurrent Streamlit sessions and MCP calls (see `test_one_compiled_graph_serves_concurrent_runs`).
2. **Declarative recon.** `pipeline.COLLECTORS` is a tuple of `CollectorSpec(name, run, progress, needs_clone, after)`. The graph is generated from it: edges come from `after`, `needs_clone` specs are skipped uniformly when there is no clone, and `defer=True` is derived from the topology (see the fan-in section).
3. **Typed state.** Nodes exchange `CollectorResult` and `CategoryFinding` objects. Only the final `Report` is converted with `to_dict()`, for exporters and interfaces.
4. **Deterministic first.** Analysts compute issues and scores in code. The LLM narrates, or adds evidence it verified with tools (the analyst contract below).
5. **Degrade, don't crash.** Every external dependency (git, GitHub, scanners, OSV, deps.dev, the LLM) can fail. When one does, only the signals that need it degrade, with a recorded reason.

## Stage 1: recon (`recon/`)

Each collector is a plain function returning `CollectorResult(name, status, data, detail)`. A collector never raises for an expected failure: it returns `skipped` or `error` with a reason. Consumers read data through `collector_data(recon, name)`, which returns None unless the status is `ok`.

| Collector | Module | Produces |
|---|---|---|
| clone | `recon/clone.py` | temp dir; shallow, size-capped, hardened (see Security model) |
| `repo_layout` | `recon/files.py` | nested tests/CI/docs/license/policies, lockfile presence, lines per language, README fallback |
| `github_metadata` | `recon/github.py` | stars, license SPDX id, activity, archived flag, README, root structure |
| `readme` | `pipeline._readme` → `recon/readme.py` | heading-based sections, examples, badges, 0–100 score; reads the API README first, then the clone |
| `static_analysis` | `recon/scanners.py` | `ruff --isolated --select E4,E7,E9,F,B,PLE`, tests excluded |
| `security` | `recon/scanners.py` + `recon/secrets.py` | bandit (tests and asserts excluded), semgrep `p/security-audit` (metrics off), secret scanner |
| `infrastructure` | `recon/infrastructure.py` | zizmor over GitHub Actions workflows and Dependabot config (offline; the repo's own config and ignore comments are disabled), hadolint over Dockerfiles (run from a neutral directory with ignore pragmas disabled), and a built-in check for containers that never drop root |
| `dependency_audit` | `recon/dependencies.py` + `recon/manifests.py` | OSV `querybatch` → advisory details → deps.dev licenses, all bounded and cached |

Scanners run with `cwd` set to the clone, and every path is rewritten repo-relative by `recon.files.relative_posix`.

**Dependencies: exact versions only.** `manifests.py` parses `requirements*.txt`, `pyproject.toml` (PEP 621, dependency groups, Poetry), `package.json`, `uv.lock`, `poetry.lock` and `package-lock.json`. Only `==` pins and lockfile entries are audited, because a range's lower bound says nothing about what gets installed. Ranges go to `unpinned`. A lockfile replaces its own ecosystem's manifests in the same directory. Packages are classified dev-only or runtime (for `uv.lock`, by the transitive closure of the project's runtime dependencies), and the analyst lowers dev-only advisories by two severity levels. License lookups cover runtime packages only.

**Secrets.** Provider-specific patterns, plus a generic assignment rule with an entropy floor and placeholder filter. Values are never reported. Hits under `tests/`, `fixtures/`, `examples/` and similar directories are LOW, since test suites routinely commit throwaway keys.

Every agent's job, inputs, tools and bounds are documented in [agents.md](agents.md); their prompts are the markdown files in `agents/instructions/`.

Agent findings pass a deterministic grounding check (`agents/grounding.py`) before they are merged: fabricated citations are dropped, and unverifiable ones are capped at low severity. See [agents.md](agents.md#grounding-check).

## Stage 2: planner (`agents/planner.py`)

`LeadInvestigator` makes one structured-output call. The output model uses `Literal`-typed fields so the model can't invent categories or depths. The prompt contains recon counts (`pipeline.recon_summary`), the user's context, and a cap: "at most N deep categories".

The budget is reserved before the fan-out. The planner node computes `N = budget.affordable_count(estimated_tokens_per_deep_investigation)`, and `enforce_deep_cap` drops extra deep picks in this order: security > dependencies > code quality > maintainability > documentation. If the five parallel nodes checked the budget themselves, they would all see it full at once.

Planning never blocks a run. If deep mode is disabled, there is no clone, there is no LLM, or the call fails, the result is an all-shallow plan with the reason recorded in each rationale. Note that pydantic output class names must not start with `_`: Groq turns `_Foo` into `' _Foo'` and rejects the tool call.

## Stage 3: categories (`agents/analysts/`, `pipeline.Workflow.analyze_category`)

The `Analyst` contract (`analysts/base.py`):

- `assess(recon) -> Assessment` is pure code: issues (repeated findings for a rule grouped into one issue with `occurrences` and up to 20 sample `locations`), a score, a deterministic summary, and prompt-ready `narrative_facts`.
- `narrate(assessment, llm) -> CategoryFinding` makes the only LLM call on the shallow path. On failure it keeps the deterministic summary and adds a note.
- `rescore(recon, assessment, new_issues)` applies the investigator's new issues on top of the deterministic score.
- `unassessed(reason)` is used when inputs are missing. The category is then excluded from the overall score instead of counting as a fake 50.

`analyze_category` calls `assess` once, then `narrate`. If the plan says deep, it builds the tools for `analyst.tool_families` and calls `investigate(...)`, passing the known issues so the agent doesn't repeat them. It merges the agent's new issues and rescores. If an `InvestigationError` is raised, it returns the shallow finding plus a note. Recon findings are never discarded.

**Investigator** (`agents/investigator.py`) is a ReAct loop on `langchain.agents.create_agent` (not the deprecated `langgraph.prebuilt.create_react_agent`). It has three bounds:

- steps: `recursion_limit = max_tool_calls * 2 + 4`
- wall clock: a daemon thread joined with a timeout (`ThreadPoolExecutor`'s atexit join would hang shutdown on a stuck call)
- prompt size: `summarize_recon_data` trims strings to 1500 characters and lists to 15 items

`extract_trace` rebuilds `(tool, input, observation)` triples and skips the synthetic `InvestigationOutput` call that `create_agent` uses to submit structured output.

**Tools** (`agents/tools.py`) come in four families: `files` (`read_file`, `list_directory`, `find_files`, `search_code`), `scanners` (`run_scanner_on_path`), `dependencies` (`query_osv`), and `git_history` (`get_file_git_history`, via the GitHub API because a shallow clone has one commit). `build_tools` offers only the tools that can work for this run.

## Stage 4: synthesis (`report/`)

`synthesize_report` is pure. It computes the weighted mean over assessed categories (security 0.30, code quality 0.25, others 0.15, renormalized), sorts issues, and builds deduplicated quick wins. The service then records score history: append-only, 20 runs per repository, written to a temp file and renamed into place. A thread lock and a lock file (`history.json.lock`) serialize writers, so the UI, CLI and MCP server can share one `reports/` directory. If history can't be written, the report is still returned and a warning is logged. See [report-format.md](report-format.md) for the scoring math and output schema.

## Resilience (`resilience.py`, `agents/llm.py`)

```
LLMRuntime.complete / structured / guarded
  └─ CircuitBreaker.call(          fail fast once failures are sustained (shared process-wide)
       retry_with_backoff(         one transient blip; never retries 4xx auth/size or CircuitOpenError
         client.invoke))           SDK retries disabled (max_retries=0)
```

The breaker wraps the retry loop. In half-open state it lets exactly one probe through. Calls already in flight when it opens can each fail once; every later call, including the whole next run, short-circuits.

## LangGraph fan-in gotcha

A node whose predecessors sit at different depths fires once per superstep in which any predecessor finishes, unless it has `defer=True`. `pipeline._needs_defer` decides this from `CollectorSpec.after` depths: `readme` (predecessors at depths 1 and 1) is not deferred, and `planner` (1, 1, 1, 2) is. Never defer a node that feeds another deferred node: both become pending together, the downstream node runs first, then runs again. That bug once ran every category twice; `test_every_node_runs_exactly_once` guards against it.

## Security model

**CI and container findings are bounded.** In the security score, zizmor, hadolint and container findings count on a gentler curve and can remove at most 40% (`INFRA_MAX_IMPACT`), so hardening gaps never outweigh flaws in the code itself. zizmor keeps its own severity only for directly exploitable audits (template injection, dangerous triggers, known-vulnerable actions and the like). Hardening advice such as unpinned actions is scored one level lower.

**The analyzed code is never executed.** Nothing from the clone is installed, built, imported or run. ruff, bandit and semgrep only parse source, and ruff runs `--isolated` so repository config can't disable rules. Manifests are parsed as text.

**Hardened clone** (`recon/clone.py`):

| Measure | Why |
|---|---|
| URL normalized by `RepoRef.parse`, strict name pattern, passed after `--` | no option injection, no credentials in the URL, no other hosts |
| `GIT_TERMINAL_PROMPT=0`, empty `credential.helper`, `GCM_INTERACTIVE=never`, stdin closed | private or missing repos fail fast instead of hanging on a prompt or dialog |
| `core.symlinks=false` | no file inside the clone can point outside it |
| `GIT_LFS_SKIP_SMUDGE=1`, `--depth 1 --single-branch --no-tags`, size cap, timeout | bounded download |
| removal in `finally`, read-only pack files handled on Windows | no leftovers |

**LLM-chosen tool arguments are hostile.** `resolve_safe_path` rejects `..`, absolute paths, NUL bytes and symlink escapes. Globs with `..`, absolute paths or drive letters are rejected. Regexes and all outputs are capped. Tools are read-only. Prompt injection in an analyzed README can at worst skew that category's narrative or its agent-sourced issues (which carry `source: investigator:<category>`). It cannot touch deterministic findings or scores.

**Data that leaves the machine:** public repository metadata to GitHub, package names and versions to OSV.dev and deps.dev, and trimmed recon data plus tool outputs to the configured LLM provider. Secrets are never reported by value.

**Exposed services:** the web UI, the health API and the MCP HTTP transport have no authentication. They bind to localhost by default, and `docker-compose.yml` publishes their ports on `127.0.0.1` only. Put an authenticating proxy in front before exposing them.

**Container:** non-root (uid 1000), with code and tools root-owned and read-only to the app user; only `reports/` and `logs/` are writable. No curl in the image (healthchecks use Python), and the build context is an allow-list (`.dockerignore`), so local `.env` files never reach the build.

## Interfaces (`interfaces/`)

- **cli**: argparse subcommands. Progress goes to stderr and the report to stdout, so `--json` can be piped.
- **streamlit_app**: runs the analysis on a worker thread that writes to a plain `AnalysisJob` object. `st.fragment(run_every=1)` shows progress and reruns once when the job finishes. `main()` runs only under `__main__`.
- **mcp_server**: `MCPServer` (MCP Python SDK 2). The analysis runs in a worker thread and progress becomes MCP progress notifications (best-effort).
- **health**: token-free connectivity checks plus the FastAPI app (sync endpoints, lazy config).
