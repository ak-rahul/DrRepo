"""Smoke tests for the Streamlit UI via Streamlit's own AppTest harness."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "src" / "drrepo" / "interfaces" / "streamlit_app.py"


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here, no logs written into the repo
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    return at


def test_initial_render(app):
    assert not app.exception
    assert app.title[0].value == "🩺 DrRepo"
    assert app.text_input[0].label == "GitHub repository URL"
    assert "GROQ_API_KEY not set" in app.info[0].value  # no-LLM mode is explained, not an error


def test_importing_has_no_side_effects():
    import drrepo.interfaces.streamlit_app as module

    assert callable(module.main)


def test_invalid_url_shows_error(app):
    app.text_input[0].input("https://gitlab.com/a/b")
    app.button[0].click().run()  # the form submit button
    assert any("github.com" in e.value for e in app.error)
