# Development

## Setup

```bash
uv sync                          # runtime + dev group (pytest, mypy, pre-commit, pip-audit)
uv tool install semgrep          # optional; only the live integration tests run it
uv run pre-commit install
```

uv is the only supported package manager. Change dependencies with `uv add <pkg>` or `uv add --dev <pkg>` and commit `uv.lock`; CI runs `uv sync --locked`.

Never add semgrep back as a project dependency. It hard-pins `mcp`, `opentelemetry` and `wcmatch` to versions with known CVEs, and those pins hold DrRepo's own MCP server back. It is installed as an isolated uv tool instead (locally, in CI's integration job, and in the Docker image), and `recon/scanners.find_executable` finds it on `PATH`.

## Commands

```bash
uv run pytest                                   # unit tests: hermetic, ~10 s
uv run pytest tests/test_pipeline.py            # one file
uv run pytest tests/test_pipeline.py::test_every_node_runs_exactly_once
uv run pytest -k dependencies                   # by keyword
uv run pytest -m integration -v                 # live: network, git, API keys (skip themselves if missing)
uv run pytest --cov                             # coverage (path-based; see pyproject)
uv run ruff check src tests examples            # lint
uv run ruff format src tests examples           # format
uv run mypy src examples                        # types
```

Before pushing, run `uv run pre-commit run --all-files` (ruff, strict mypy, uv.lock sync, zizmor/actionlint for workflows, hadolint for the Dockerfile, schema checks for workflows, Dependabot and compose) and `uv run pytest`. That is what CI's lint and test jobs run. CI also builds the wheel and sdist, checks them with `twine`, installs the wheel into a clean venv, and builds and smoke-tests the Docker image.

mypy runs in `strict` mode over `src/` and `examples/`. Supported Python versions are 3.11 to 3.14, and all of them are in the CI matrix.

## Tests

- `tests/` mirrors `src/drrepo/`: top-level modules map to `tests/test_<module>.py`, and packages to `tests/recon/`, `tests/agents/`, `tests/report/`, `tests/interfaces/`. Live tests are in `tests/integration/`.
- Unit tests are hermetic. Autouse fixtures in `tests/conftest.py` fail any real HTTP request and any real clone started by the pipeline. Use `mock_http({...})` (an `httpx.MockTransport`) or inject `http_client=`.
- Helpers: `ok(data)`, `skipped()` and `failed(detail)` build `CollectorResult`s. `make_repo({...})` creates a fake clone. Build `Config(...)` directly; nothing reads `.env`.
- Pipeline tests patch the collector functions as module attributes (`drrepo.pipeline.collect_security`, ...) and pass their own `RunContext`.
- The investigator is tested by mocking `create_agent` with real `AIMessage`/`ToolMessage` objects (`GenericFakeChatModel` has no `bind_tools`). `tests/agents/test_agent_loop.py` additionally runs the *real* `create_agent` loop, real tools on a temporary clone, and the real planner, using `ScriptedChatModel`, a `BaseChatModel` that calls `read_file` and then submits `InvestigationOutput`. Extend it when changing the investigator or planner. The live provider check is in `tests/integration/test_live.py`.
- A plain `Mock()` auto-vivifies `usage_metadata`. Keep the `isinstance(..., dict)` guards in `extract_actual_tokens`.
- The Streamlit UI is smoke-tested with `streamlit.testing.v1.AppTest`.
- `tests/test_examples.py` imports every script in `examples/` and tests its logic. Examples are linted and type-checked like `src/`.

## Extending

**A collector.** Write `collect_<name>(...) -> CollectorResult` in `recon/`, documenting the `data` schema in its docstring and returning `skipped`/`error` with a `detail` rather than raising. Add a `CollectorSpec` to `pipeline.COLLECTORS` (set `needs_clone`, and `after` if it consumes another collector's output). The graph wiring and `defer` are derived automatically. Read its output in an analyst with `collector_data(recon, "<name>")`. [examples/custom_collector.py](../examples/custom_collector.py) is a complete, tested walk-through.

**An agent's behaviour.** Edit its markdown in `src/drrepo/agents/instructions/` (format and guidelines in [agents.md](agents.md#the-instruction-files)); no Python change is needed. Rules for every category go in `shared.md`.

**A check in a category.** Add it to that analyst's `assess()`. Give each issue a stable `source` and `rule_id`: SARIF rule ids are `source/rule_id`, so a new source must not collide with an existing one.

**An investigator tool.** Add a `make_<x>_tools(...)` factory to `agents/tools.py`, register its family in `TOOL_FAMILIES`/`build_tools`, and list the family in the relevant analysts' `tool_families`. Treat every argument as hostile, and cap the output.

**An interface.** Call `AnalysisService`, never `Workflow` directly. The service owns the shared breaker, cache and client, builds a per-run `RunContext`, and records history.

## Releasing

Bump `version` in `pyproject.toml` (`drrepo.__version__` reads the installed metadata) and move the `Unreleased` entries in [CHANGELOG.md](../CHANGELOG.md) under the new version. Then run `uv lock`, run the checks above, and tag `vX.Y.Z`.
