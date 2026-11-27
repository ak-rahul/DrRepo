# Development

## Setup

```bash
uv sync                          # runtime + dev group (pytest, mypy, pre-commit, pip-audit)
uv run pre-commit install
```

uv is the only supported package manager. Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`), never by hand-editing a requirements file. `uv.lock` is committed, and CI runs `uv sync --locked`.

## Everyday commands

```bash
uv run pytest                              # unit tests: hermetic, ~10 s
uv run pytest -m integration -v            # live: network, git, API keys (skip themselves if missing)
uv run pytest --cov=drrepo                 # coverage
uv run ruff check src tests                # lint (pycodestyle, pyflakes, isort, bugbear, bandit rules, ...)
uv run ruff format src tests               # format
uv run mypy src                            # types
```

`make check` runs lint, typecheck, tests, and the format check. Every Makefile target is a single `uv` command, so you can copy it on systems without `make`.

## Test conventions

- `tests/` mirrors `src/drrepo/` (`collectors/`, `agents/`, `tools/`, `pipeline/`, `report/`, `interfaces/`).
- Unit tests are hermetic. An autouse fixture in `tests/conftest.py` makes any real HTTP request fail. Use `mock_http({...})` (an `httpx.MockTransport`) or inject an `http_client`.
- Fixtures build `Config(...)` directly. Nothing reads `.env`.
- `make_repo({...})` creates a fake clone in `tmp_path`.
- The investigator is tested by mocking `create_agent` and feeding real `AIMessage`/`ToolMessage` objects. `GenericFakeChatModel` has no `bind_tools`. The live tool-calling check is in `tests/integration/test_live.py`.
- Gotcha: a plain `Mock()` auto-vivifies `usage_metadata`. `extract_actual_tokens` guards with `isinstance(..., dict)`. Keep that guard.
- The Streamlit UI is smoke-tested with `streamlit.testing.v1.AppTest`.

## Extending DrRepo

**A new collector**

1. Add `collectors/<name>.py` with `collect_<name>(...) -> CollectorResult`. Document the `data` schema in the module docstring. Return `skipped`/`error` with a `detail` instead of raising.
2. Add a node in `pipeline/workflow.py` and wire its edges. If it feeds a multi-predecessor node at a different depth, read the fan-in section of [architecture.md](architecture.md) before using `defer=True`.
3. Read it in an analyst via `collector_data(recon, "<name>")`, which returns None unless status is `ok`.

**A new check inside a category:** add it to that analyst's `assess()`. Give each issue a stable `source` and `rule_id`: they become the SARIF rule id `source/rule_id`, and a new source must not collide with an existing one.

**A new investigator tool:** write a `make_<x>_tools(...)` factory in `tools/`, register its family in `tools/registry.py`, and add the family to the relevant analysts' `tool_families`. Treat every argument as hostile (see [security.md](security.md)). Cap output size.

**A new interface:** call `AnalysisService`. Don't build `Workflow` directly. The service owns the shared breaker and cache, history recording, and the per-run budget.

## Releasing

1. Bump `version` in `pyproject.toml`. `drrepo.__version__` reads the installed metadata, so there is no second copy.
2. `uv lock`, then `make check`, then tag `vX.Y.Z`.
