# Architecture

DrRepo runs one LangGraph workflow per analysis. Recon collectors gather facts, a planner agent decides where to look harder, the category nodes each run shallow or deep, and a synthesizer builds the report. The CLI, Streamlit UI, and MCP server all call the same `AnalysisService`.

```
                         AnalysisService  (one per process: shares breaker + cache)
                                │  fresh Workflow + fresh token budget per run
                                ▼
 execute(url) ── parse URL ── clone (outside the graph, try/finally cleanup)
                                │
 ┌────────────────────────── LangGraph ─────────────────────────────────────┐
 │ START ─┬─ repo_layout ──────┐                                            │
 │        ├─ github_metadata ──┴─► readme ──┐                               │
 │        ├─ static_analysis ───────────────┤                               │
 │        ├─ security ──────────────────────┼─► planner (defer) ─┬─► documentation ─┐
 │        └─ dependency_audit ──────────────┘                    ├─► code_quality ──┤
 │                                                               ├─► security_review┼─► synthesizer (defer) ─► END
 │                                                               ├─► dependency_review
 │                                                               └─► maintainability┘
 └──────────────────────────────────────────────────────────────────────────┘
```

## Package layout

```
src/drrepo/
  config.py            Config dataclass; Config.from_env() is the only os.environ reader
  models.py            Issue, CategoryFinding, InvestigationPlan, Report, ...
  service.py           AnalysisService: façade used by every interface
  cli.py               drrepo analyze | ui | mcp | health | doctor | health-api
  core/                log, errors, retry, circuit_breaker, budget, cache, github_url
  collectors/          deterministic recon: clone, github, layout, readme, scanners,
                       static_analysis, security, manifests, dependencies, filesystem
  agents/
    llm.py             build_chat_model + LLMRuntime (guarded calls)
    planner.py         LeadInvestigator
    investigator.py    bounded ReAct investigation
    analysts/          one Analyst per category (base.py defines the contract)
  tools/               LangChain tools for investigators + registry.build_tools
  pipeline/            LangGraph State and Workflow
  report/              synthesizer, exporters (json/md/sarif), history
  interfaces/          streamlit_app, mcp_server, health_api, health_checks
```

Package `__init__.py` files hold docstrings and nothing else (`agents/analysts/__init__.py` also exposes `default_analysts()`). Import from the submodule you need. That keeps `import drrepo.models` from pulling in LangChain, Streamlit, and the rest of the stack.

## Stage 1: recon collectors

Each collector is a plain function returning a `CollectorResult(name, status, data, detail)`. A collector never raises for an expected failure. It reports `skipped` or `error` with a reason, and downstream consumers check `status` (via `collector_data()`) before trusting `data`.

| Collector | Needs | Produces |
|---|---|---|
| `clone.clone_repo` | `git` | temp dir. Shallow (`--depth 1`), size-capped, hardened (see [security.md](security.md)) |
| `layout.collect_repo_layout` | clone | nested test/CI/docs/license/policy detection, lockfile presence, lines per language, README fallback |
| `github.collect_github_metadata` | GitHub API | stars, license SPDX id, activity, archived flag, README text, root structure |
| `readme.analyze_readme` | README text (API first, clone second) | headings-based section detection, examples, badges, 0–100 quality score |
| `static_analysis` | clone + ruff | `ruff --isolated --select E4,E7,E9,F,B,PLE` (the repo's own config is ignored so it can't switch rules off) |
| `security` | clone | bandit (tests and asserts excluded), semgrep `p/security-audit` with metrics off, secret scanner |
| `dependencies` | clone + network | OSV `querybatch` → advisory details → deps.dev licenses, all bounded and cached |

Every scanner runs with `cwd` set to the clone, and every reported path is rewritten to a repo-relative POSIX path by `filesystem.relative_posix`. Reports and SARIF never point at a temp directory that no longer exists.

### Dependencies: exact versions only

`collectors/manifests.py` parses `requirements*.txt`, `pyproject.toml` (PEP 621, dependency groups, Poetry), `package.json`, `uv.lock`, `poetry.lock`, and `package-lock.json`.

- Only exact versions are audited: `==` pins and lockfile entries. Querying OSV for the lower bound of `>=2.0` would report advisories the project may not be exposed to. Ranges are recorded as `unpinned` instead.
- A lockfile replaces its own ecosystem's manifests in the same directory.
- Each package is classified as dev-only or runtime. The rules use dependency groups, `devDependencies`, `requirements-dev.txt`, package-lock's `dev` flag, and, for `uv.lock`, the transitive closure of the project's runtime dependencies. The analyst lowers dev-only advisories by two severity levels, since a vulnerable test runner rarely reaches users. Without this, a well-maintained library scored 3/100 for dependencies because of its pytest pin.

## Stage 2: Lead Investigator (planner)

`agents/planner.py` makes one structured-output call (`InvestigationPlanOutput`, with `Literal`-typed fields so the model can't invent depths). The prompt includes recon counts, any user context, and a cap: "at most N deep categories".

**Budget is reserved before fan-out.** The five category nodes run in parallel. If each checked the token budget itself, all five would see a full budget at the same moment and all go deep. The planner node computes `N = budget.affordable_count(estimated_tokens_per_deep_investigation)` up front, and `enforce_deep_cap` drops the lowest-priority deep picks in this order: security > dependencies > code quality > maintainability > documentation.

Planning never blocks a run. Any failure, including an open circuit breaker, produces an all-shallow plan with the reason recorded in each rationale.

**Naming gotcha (verified live against Groq):** pydantic output classes must not start with an underscore. Groq mangles `_Foo` into `' _Foo'` and rejects the tool call.

## Stage 3: category nodes and the analyst contract

Each category has an `Analyst` (`agents/analysts/`). The contract in `base.py` is the core design rule of the project:

1. **Deterministic first.** `assess(recon)` turns collector data into `Issue`s and a score with plain code. File, line, rule, and severity always come from a tool, never from LLM text. Repeated findings for the same rule are grouped into one issue with `occurrences` and up to 20 sample `locations`.
2. **The LLM narrates.** On the shallow path the only LLM call writes the summary. If it fails, the deterministic summary is used and a note is attached (`"LLM summary unavailable (CircuitOpenError)"`).
3. **Deep adds evidence.** On the deep path the investigator gets the analyst's prompt, the tool families it is allowed to use, trimmed recon data, and the list of already-known issues so it doesn't repeat them. Its new issues are merged with the deterministic ones, and the analyst re-scores the union (`rescore`). Recon findings are never discarded. If the investigation fails, the node returns the shallow result plus a note explaining why.
4. **Unassessable is not 50.** When a category's inputs are missing (README unavailable, no Python code for ruff, OSV down), the finding is `assessed=False`. Its score is excluded from the overall score instead of being counted as a neutral 50.

### Investigator (`agents/investigator.py`)

The investigator is built on `langchain.agents.create_agent` (`langgraph.prebuilt.create_react_agent` is deprecated). Three limits apply to every run:

| Limit | Mechanism |
|---|---|
| steps | `recursion_limit = max_tool_calls * 2 + 4`; exhaustion raises `GraphRecursionError` |
| wall clock | a daemon thread joined with a timeout. `ThreadPoolExecutor`'s atexit join would hang interpreter shutdown on a stuck call |
| prompt size | `summarize_recon_data` trims strings to 1500 chars and lists to 15 items, recursively. One untrimmed prompt was once observed requesting ~112k tokens |

Every failure is raised as an `InvestigationError(reason)`. `extract_trace` rebuilds `(tool, input, observation)` triples from the message history. It skips the synthetic `InvestigationOutput` tool call that `create_agent` uses to submit structured output.

### Tools (`tools/`)

| Family | Tools | Notes |
|---|---|---|
| files | `read_file`, `list_directory`, `find_files`, `search_code` | every path goes through `resolve_safe_path`; globs containing `..`, absolute paths, or drive letters are rejected |
| scanners | `run_scanner_on_path` | the same wrappers as recon, so both views agree |
| dependencies | `query_osv` | exact version, with severity and fixed versions (shared with the MCP tool) |
| git_history | `get_file_git_history` | GitHub API, since local history is a single commit in a shallow clone |

`tools/registry.build_tools(families, ...)` offers only tools that can work for the run: no clone means no file or scanner tools, and no `owner/repo` means no git history.

## Stage 4: synthesis

`report/synthesizer.py` is a pure function. It takes the weighted mean over assessed categories (security 0.30, code quality 0.25, the others 0.15 each, renormalized), sorts issues by severity and occurrence count, deduplicates quick wins, and adds the plan, timestamps, and version. History (`report/history.py`) lives outside the synthesizer on purpose: it is the one place a report touches disk other than export, and it writes atomically (temp file + `os.replace`).

## Resilience: LLM layering

```
LLMRuntime.complete / structured / guarded
   └─ CircuitBreaker.call(           ← fail fast once failures are sustained
        retry_with_backoff(          ← absorb one transient blip; never retries 4xx auth/size errors
          client.invoke))            ← SDK retries disabled (max_retries=0)
```

The breaker wraps the retry loop, never the reverse. With retry outside, every attempt would pay the full backoff against an already-open circuit. The breaker is shared by all parallel nodes and, through `AnalysisService`, across runs: one dead quota short-circuits every later call. A half-open breaker lets exactly one probe through, so a recovering provider isn't hit by five parallel probes.

The token budget is per run. `Workflow.execute` resets it. A shared, never-reset budget would silently disable deep mode for good after a few runs in a long-lived process.

## LangGraph fan-in gotcha

A node whose predecessors sit at different depths fires once per superstep in which any predecessor finishes, not once after all of them. `planner` waits on `readme` (depth 2) and three depth-1 collectors, so it needs `defer=True`. `synthesizer` has it too, as a guard.

Don't defer a node that feeds another deferred node. `readme` was once deferred as well. Both nodes became pending in the same superstep, the planner ran first, then ran again once `readme` finished, and every category ran twice. `tests/pipeline/test_workflow.py::test_every_node_runs_exactly_once` guards against this.

## Interfaces

All interfaces go through `AnalysisService`:

- **CLI** (`cli.py`): argparse subcommands. Progress goes to stderr and the report to stdout, so `--json` output can be piped.
- **Streamlit** (`interfaces/streamlit_app.py`): the job runs on a background thread that writes to a plain `AnalysisJob` object (not `st.session_state`, which needs a script-run context the thread lacks). A `st.fragment(run_every=1)` shows progress and triggers one full rerun when the job finishes. Connectivity checks run only on demand.
- **MCP** (`interfaces/mcp_server.py`): FastMCP. The analysis runs in a worker thread and progress is forwarded as MCP progress notifications. See [mcp.md](mcp.md).
- **Health API** (`interfaces/health_api.py`): sync endpoints, so blocking checks don't stall the event loop. Config loads lazily on first request.
