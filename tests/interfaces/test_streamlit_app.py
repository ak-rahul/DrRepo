"""Smoke tests for the Streamlit UI via Streamlit's own AppTest harness."""

import time
from pathlib import Path
from types import SimpleNamespace

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


REPORT = {
    "repository": {
        "name": "demo",
        "full_name": "octo/demo",
        "description": "A demo repository",
        "stars": 1234,
        "language": "Python",
    },
    "overall_score": 72.4,
    "issue_counts": {"critical": 0, "high": 1, "medium": 0, "low": 1},
    "category_scores": {
        "security": {
            "score": 60.0,
            "assessed": True,
            "investigation_depth": "deep",
            "summary": "One shell injection.",
            "notes": ["Deep investigation hit its tool-call cap."],
            "investigation_trace": [
                {"tool": "read_file", "tool_input": {"path": "a.py"}, "observation": "x = 1"}
            ],
        },
        "documentation": {
            "score": 0.0,
            "assessed": False,
            "investigation_depth": "shallow",
            "summary": "No README source.",
            "notes": [],
            "investigation_trace": [],
        },
    },
    "issues": [
        {
            "severity": "high",
            "category": "security",
            "title": "Shell injection",
            "description": "d",
            "recommendation": "Avoid shell=True",
            "source": "bandit",
            "rule_id": "B602",
            "file": "a.py",
            "line": 3,
            "locations": [{"file": "a.py", "line": 3}, {"file": "b.py", "line": 9}],
            "occurrences": 2,
        },
        {
            "severity": "low",
            "category": "documentation",
            "title": "No changelog",
            "description": "d",
            "recommendation": "Add one",
            "source": "layout",
            "rule_id": None,
            "file": None,
            "line": None,
            "locations": [],
            "occurrences": 1,
        },
    ],
    "quick_wins": ["Avoid shell=True"],
    "investigation_plan": {"security": {"depth": "deep", "rationale": "bandit HIGH"}},
    "collector_status": {"security": {"status": "ok", "detail": None}},
    "score_history": {
        "overall_score_delta": 4.2,
        "previous_timestamp": "2026-11-01T10:00:00+00:00",
        "category_score_deltas": {"security": -5.0},
    },
    "llm_usage": {"used_tokens": 1200, "max_tokens": 50000, "remaining_tokens": 48800},
}


def _job(status, result=None, error=None):
    # Duck-typed AnalysisJob: the script's own class lives in its __main__ namespace.
    return SimpleNamespace(
        repo_url="https://github.com/octo/demo",
        started_at=0.0,
        messages=["Cloning octo/demo"],
        status=status,
        result=result,
        error=error,
    )


def _run_with_job(job):
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["job"] = job
    at.session_state["job_shown"] = True
    at.run()
    assert not at.exception
    return at


def test_finished_job_renders_full_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = _run_with_job(_job("done", REPORT))
    markdown = " ".join(m.value for m in at.markdown)
    assert "octo/demo" in markdown
    assert "Quick wins" in markdown and "Lead Investigator's plan" in markdown
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Overall score"] == "72/100 (C)"
    assert metrics["Documentation"] == "n/a"  # unassessed: shown, not scored
    assert metrics["🕵️ Security"] == "60"  # deep-investigated category is marked
    assert any("Shell injection" in e.label and "×2" in e.label for e in at.expander)
    assert any("LLM usage" in c.value for c in at.caption)


def test_failed_job_shows_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = _run_with_job(_job("error", error="CloneError: repository not found"))
    assert any("repository not found" in e.value for e in at.error)


def test_start_job_records_result_and_errors():
    import drrepo.interfaces.streamlit_app as module

    class Service:
        def __init__(self, fail):
            self.fail = fail

        def analyze(self, repo_url, description, *, deep, progress, ref=None):
            progress("working")
            if self.fail:
                raise RuntimeError("boom")
            return {"repo": repo_url, "deep": deep}

    def wait(job):
        for _ in range(200):
            if job.status != "running":
                return job
            time.sleep(0.01)
        raise AssertionError("job never finished")

    done = wait(module.start_job(Service(False), "https://github.com/a/b", "", deep=True))
    assert (done.status, done.result, done.messages) == (
        "done",
        {"repo": "https://github.com/a/b", "deep": True},
        ["working"],
    )
    failed = wait(module.start_job(Service(True), "https://github.com/a/b", "", deep=False))
    assert (failed.status, failed.error) == ("error", "RuntimeError: boom")
