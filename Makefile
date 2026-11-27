# Thin convenience wrapper: every target is a plain `uv` command, so Windows
# users without `make` can copy the command directly.
.PHONY: help install lint format typecheck test test-integration cov check ui mcp doctor docker clean
.DEFAULT_GOAL := help

help:
	@echo "install           uv sync + pre-commit hooks"
	@echo "lint / format     ruff check / ruff format"
	@echo "typecheck         mypy src"
	@echo "test              unit tests (hermetic)"
	@echo "test-integration  live tests (network + API keys)"
	@echo "cov               unit tests with coverage report"
	@echo "check             lint + format check + typecheck + test"
	@echo "ui / mcp / doctor run the Streamlit UI / MCP server / diagnostics"
	@echo "docker            build the image"

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src

test:
	uv run pytest

test-integration:
	uv run pytest -m integration -v

cov:
	uv run pytest --cov=drrepo --cov-report=term --cov-report=html

check: lint typecheck test
	uv run ruff format --check src tests

ui:
	uv run drrepo ui

mcp:
	uv run drrepo mcp

doctor:
	uv run drrepo doctor

docker:
	docker build -t drrepo:latest .

clean:
	uv run python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'dist', 'build', *map(str, pathlib.Path('.').rglob('__pycache__'))]]"
