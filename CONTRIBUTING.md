# Contributing to DrRepo

Thanks for helping. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

```bash
git clone https://github.com/<you>/DrRepo && cd DrRepo
uv sync
uv run pre-commit install
uv run pytest
```

[uv](https://docs.astral.sh/uv/) is the only supported package manager. Use `uv add` / `uv add --dev` to change dependencies, and commit the updated `uv.lock`.

## Making a change

1. Create a branch from `main`.
2. Keep changes focused, and add or update tests next to the code (`tests/` mirrors `src/drrepo/`).
3. Make sure the CI checks pass: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest`.
4. Unit tests must stay hermetic: no network, no environment variables. Anything live belongs in `tests/integration/` with `@pytest.mark.integration`.
5. Use [Conventional Commits](https://www.conventionalcommits.org) messages (`feat:`, `fix:`, `docs:`, ...).
6. Open a pull request that says what changed and why.

[docs/development.md](docs/development.md) explains how to add a collector, an analyst check, an investigator tool, or a new interface, and lists the design rules a review will check: deterministic findings first, tools treat their arguments as hostile, nothing executes the analyzed code.

## Reporting bugs and requesting features

Open a GitHub issue. For bugs, include the `uv run drrepo doctor` output, the command you ran, and the relevant part of `logs/app.log` with tokens removed. Report security problems privately to the maintainer, not in a public issue.
