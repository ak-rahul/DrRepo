"""Live checks against real services. Run with `uv run pytest -m integration`.

These need network access and (for the LLM tests) a real GROQ_API_KEY/GH_TOKEN
in the environment or `.env`; each test skips itself when its inputs are missing.
"""

from __future__ import annotations

import shutil

import pytest

from drrepo.config import Config

pytestmark = pytest.mark.integration

SMALL_REPO = "https://github.com/pallets/itsdangerous"


@pytest.fixture(scope="module")
def live_config() -> Config:
    return Config.from_env()


@pytest.fixture(autouse=True)
def _no_real_network():
    """Override the unit-suite network block: these tests are supposed to hit the network."""
    yield


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_deterministic_analysis_of_real_repo(live_config):
    from dataclasses import replace

    from drrepo.service import AnalysisService

    config = replace(live_config, groq_api_key="", openai_api_key="", enable_score_history=False)
    report = AnalysisService(config).analyze(SMALL_REPO)
    assert report["repository"]["full_name"] == "pallets/itsdangerous"
    assert report["collector_status"]["repo_clone"]["status"] == "ok"
    assert 0 < report["overall_score"] <= 100


def test_osv_lookup_finds_known_vulnerability(live_config):
    from drrepo.tools.dependencies import lookup_package

    out = lookup_package("jinja2", "PyPI", "2.4.1", live_config)
    assert "GHSA-" in out or "PYSEC-" in out


def test_investigator_really_calls_tools(live_config, tmp_path):
    if live_config.validate_for_llm():
        pytest.skip("no LLM API key configured")
    from drrepo.agents.investigator import investigate
    from drrepo.agents.llm import LLMRuntime, build_chat_model
    from drrepo.models import Category
    from drrepo.tools.files import make_file_tools

    (tmp_path / "app.py").write_text(
        "import os\n\ndef run(cmd):\n    os.system(cmd)\n", encoding="utf-8"
    )
    result = investigate(
        category=Category.SECURITY,
        system_prompt="You are investigating security. Read app.py and report command injection risks.",
        tools=make_file_tools(str(tmp_path)),
        llm=LLMRuntime(client=build_chat_model(live_config)),
        recon_data={},
        known_issues=[],
        max_tool_calls=4,
        timeout_seconds=120,
    )
    assert result.trace, "the agent should have called at least one tool"
    assert result.summary
