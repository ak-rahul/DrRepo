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


def test_report_tabs_and_untrusted_text(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    report = dict(REPORT)
    report["issues"] = [
        dict(REPORT["issues"][0], title="Pixel ![x](https://evil.example/p.png)", description="$x$")
    ]
    report["dependencies"] = [
        {
            "ecosystem": "PyPI",
            "name": "jinja2",
            "version": "3.1.2",
            "scope": "runtime",
            "license": "MIT",
            "vulnerabilities": ["GHSA-1"],
        }
    ]
    report["suppressed"] = [
        {
            "issue": REPORT["issues"][1],
            "suppression": {
                "rule": "layout",
                "path": None,
                "reason": "ok",
                "expires": None,
                "origin": "local",
            },
        }
    ]
    report["category_scores"] = dict(
        REPORT["category_scores"],
        security=dict(REPORT["category_scores"]["security"], investigation_depth="lite"),
    )
    at = _run_with_job(_job("done", report))
    labels = [e.label for e in at.expander]
    assert any(r"\!\[x\]\(https://evil.example/p.png\)" in label for label in labels)
    assert not any("![x](" in label for label in labels)  # never an image
    assert r"\$x\$" in " ".join(m.value for m in at.markdown)
    assert {t.label for t in at.tabs} >= {"Dependencies", "Suppressed (1)", "Details"}
    assert "🔎 Security" in {m.label for m in at.metric}  # lite has its own marker
    assert {b.label for b in at.get("download_button")} >= {"SBOM", "Summary"}


def test_compare_mode_needs_a_base(app):
    app.radio[0].set_value("Compare two commits").run()
    app.text_input[0].input("https://github.com/octo/demo")
    app.button[0].click().run()
    assert any("needs a base" in e.value for e in app.error)


def test_finished_diff_renders(monkeypatch, tmp_path):
    from drrepo.report.diff import diff_reports

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    head = dict(REPORT, overall_score=60.0)
    head["issues"] = [dict(REPORT["issues"][0], title="New one", rule_id="B9")]
    diff = {**diff_reports(REPORT, head), "head_report": head}
    at = _run_with_job(_job("done", diff))
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["New issues"] == "1" and metrics["Fixed"] == "2"
    assert any("New one" in e.label for e in at.expander)
    assert "Head commit report" in " ".join(m.value for m in at.markdown)


def test_recent_analyses_open_from_the_service(monkeypatch, tmp_path):
    from drrepo.service import AnalysisService

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setattr(AnalysisService, "list_reports", lambda self: [{"repository": "octo/demo"}])
    monkeypatch.setattr(AnalysisService, "latest_report", lambda self, repo: REPORT)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.sidebar.selectbox[0].set_value("octo/demo").run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Overall score"] == "72/100 (C)"


def test_start_compare_job_calls_the_service():
    import drrepo.interfaces.streamlit_app as module

    class Service:
        def compare(self, repo_url, base, head, description, *, deep, progress):
            progress("comparing")
            return {"base": base, "head": head, "deep": deep}

    job = module.start_compare_job(Service(), "https://github.com/a/b", "main", None, "", True)
    for _ in range(200):
        if job.status != "running":
            break
        time.sleep(0.01)
    assert (job.kind, job.status, job.result) == (
        "compare",
        "done",
        {"base": "main", "head": None, "deep": True},
    )


def test_mark_as_false_positive_writes_a_suppression(monkeypatch, tmp_path):
    from drrepo.report.suppressions import load_file
    from drrepo.service import AnalysisService

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setattr(AnalysisService, "list_reports", lambda self: [{"repository": "octo/demo"}])
    monkeypatch.setattr(AnalysisService, "latest_report", lambda self, repo: REPORT)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.sidebar.selectbox[0].set_value("octo/demo").run()
    reason = next(t for t in at.text_input if t.key and t.key.endswith("-issue-1-0-reason"))
    reason.input("Launches the pager by design")
    submit = next(b for b in at.button if b.label == "Add suppression")
    submit.click().run()
    assert not at.exception
    assert any(".drrepo.toml" in s.value for s in at.success)
    [entry] = load_file(tmp_path / ".drrepo.toml")
    assert (entry.rule, entry.path, entry.reason) == (
        "bandit/B602",
        "a.py",
        "Launches the pager by design",
    )
