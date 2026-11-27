# Development

## Setup

```bash
uv sync                          # runtime + dev group (pytest, mypy, pre-commit, pip-audit)
uv run pre-commit install
```

uv is the only supported package manager. Change dependencies with `uv add <pkg>` or `uv add --dev <pkg>` and commit `uv.lock`; CI runs `uv sync --locked`.

## Commands

```bash
uv run pytest                                   # unit tests: hermetic, ~10 s
uv run pytest tests/test_pipeline.py            # one file
uv run pytest tests/test_pipeline.py::test_every_node_runs_exactly_once
uv run pytest -k dependencies                   # by keyword
uv run pytest -m integration -v                 # live: network, git, API keys (skip themselves if missing)
uv run pytest --cov=drrepo                      # coverage
uv run ruff check src tests                     # lint
uv run ruff format src tests                    # format
uv run mypy src                                 # types
```

Before pushing, run the same checks as CI: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest`.

## Tests

- `tests/` mirrors `src/drrepo/`: top-level modules map to `tests/test_<module>.py`, and packages to `tests/recon/`, `tests/agents/`, `tests/interfaces/`. Live tests are in `tests/integration/`.
- Unit tests are hermetic. Autouse fixtures in `tests/conftest.py` fail any real HTTP request and any real clone started by the pipeline. Use `mock_http({...})` (an `httpx.MockTransport`) or inject `http_client=`.
- Helpers: `ok(data)`, `skipped()` and `failed(detail)` build `CollectorResult`s. `make_repo({...})` creates a fake clone. Build `Config(...)` directly; nothing reads `.env`.
- Pipeline tests patch the collector functions as module attributes (`drrepo.pipeline.collect_security`, ...) and pass their own `RunContext`.
- The investigator is tested by mocking `create_agent` with real `AIMessage`/`ToolMessage` objects (`GenericFakeChatModel` has no `bind_tools`). The live check is in `tests/integration/test_live.py`.
- A plain `Mock()` auto-vivifies `usage_metadata`. Keep the `isinstance(..., dict)` guards in `extract_actual_tokens`.
- The Streamlit UI is smoke-tested with `streamlit.testing.v1.AppTest`.

## Extending

**A collector.** Write `collect_<name>(...) -> CollectorResult` in `recon/`, documenting the `data` schema in its docstring and returning `skipped`/`error` with a `detail` rather than raising. Add a `CollectorSpec` to `pipeline.COLLECTORS` (set `needs_clone`, and `after` if it consumes another collector's output). The graph wiring and `defer` are derived automatically. Read its output in an analyst with `collector_data(recon, "<name>")`.

**A check in a category.** Add it to that analyst's `assess()`. Give each issue a stable `source` and `rule_id`: SARIF rule ids are `source/rule_id`, so a new source must not collide with an existing one.

**An investigator tool.** Add a `make_<x>_tools(...)` factory to `agents/tools.py`, register its family in `TOOL_FAMILIES`/`build_tools`, and list the family in the relevant analysts' `tool_families`. Treat every argument as hostile, and cap the output.

**An interface.** Call `AnalysisService`, never `Workflow` directly. The service owns the shared breaker, cache and client, builds a per-run `RunContext`, and records history.

## Releasing

Bump `version` in `pyproject.toml` (`drrepo.__version__` reads the installed metadata). Then run `uv lock`, run the checks above, and tag `vX.Y.Z`.
