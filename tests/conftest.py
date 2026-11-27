"""Shared fixtures. Everything is built directly -- nothing reads `os.environ` or
`.env` -- so `pytest` passes with zero environment variables set and no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from drrepo.agents.llm import LLMRuntime
from drrepo.config import Config
from drrepo.models import CollectorStatus


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a unit test accidentally opens a real HTTP connection."""

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(
            "unit tests must not make real HTTP requests; inject an httpx.MockTransport"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(autouse=True)
def _reset_drrepo_logger():
    """Tests that call configure_logging() (CLI, Streamlit) must not leak handlers."""
    from drrepo.core.log import logger

    before = list(logger.handlers)
    yield
    for handler in list(logger.handlers):
        if handler not in before:
            logger.removeHandler(handler)
            handler.close()


@pytest.fixture
def config() -> Config:
    return Config(groq_api_key="test-key", github_token="test-token", collector_timeout_seconds=30)


@pytest.fixture
def fake_chat_model() -> MagicMock:
    """A LangChain-ish chat model double: `.invoke()` returns an AIMessage-like object."""
    model = MagicMock()
    model.invoke.return_value = MagicMock(
        content="A concise LLM narrative.", usage_metadata={"total_tokens": 42}
    )
    return model


@pytest.fixture
def llm(fake_chat_model: MagicMock) -> LLMRuntime:
    return LLMRuntime(client=fake_chat_model)


def ok(data: dict[str, Any] | None = None, detail: str | None = None) -> dict[str, Any]:
    return {"status": CollectorStatus.OK.value, "data": data or {}, "detail": detail}


def skipped(detail: str = "skipped") -> dict[str, Any]:
    return {"status": CollectorStatus.SKIPPED.value, "data": {}, "detail": detail}


@pytest.fixture
def github_data() -> dict[str, Any]:
    return {
        "name": "demo",
        "full_name": "octo/demo",
        "description": "A demo repository",
        "url": "https://github.com/octo/demo",
        "stars": 120,
        "forks": 7,
        "language": "Python",
        "license_spdx_id": "MIT",
        "pushed_at": "2026-11-01T00:00:00+00:00",
        "open_issues": 3,
        "archived": False,
        "readme_content": "# Demo\n\n## Installation\n\n```\npip install demo\n```\n\n## Usage\n\nRun it.\n",
        "file_structure": {"has_tests": True, "has_ci": True, "has_license": True},
    }


@pytest.fixture
def make_repo(tmp_path: Path):
    """Create a fake clone: `make_repo({"src/a.py": "x = 1"})` -> root Path."""

    def _make(files: dict[str, str | bytes]) -> Path:
        root = tmp_path / "repo"
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        root.mkdir(exist_ok=True)
        return root

    return _make


def mock_http(routes: dict[str, Any]) -> httpx.Client:
    """httpx.Client whose responses come from `routes`: {"METHOD url-substring": json | callable}."""

    def handler(request: httpx.Request) -> httpx.Response:
        for key, value in routes.items():
            method, _, fragment = key.partition(" ")
            if request.method == method and fragment in str(request.url):
                if callable(value):
                    return value(request)
                if isinstance(value, httpx.Response):
                    return value
                return httpx.Response(
                    200, content=json.dumps(value), headers={"content-type": "application/json"}
                )
        return httpx.Response(404, json={"error": f"no mock for {request.method} {request.url}"})

    return httpx.Client(transport=httpx.MockTransport(handler))
