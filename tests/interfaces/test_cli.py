import json
from unittest.mock import MagicMock

import pytest

from drrepo.config import Config
from drrepo.interfaces import cli

REPORT = {
    "repository": {"name": "demo", "full_name": "octo/demo", "url": "https://github.com/octo/demo"},
    "overall_score": 42.0,
    "issue_counts": {"critical": 0, "high": 1, "medium": 0, "low": 0},
    "category_scores": {
        "security": {
            "score": 42,
            "assessed": True,
            "investigation_depth": "deep",
            "summary": "s",
            "notes": ["n"],
            "issues": [],
            "investigation_trace": [
                {"tool": "read_file", "tool_input": {"path": "a"}, "observation": "o"}
            ],
        },
        "code_quality": {
            "score": 0,
            "assessed": False,
            "investigation_depth": "shallow",
            "summary": "s",
            "notes": [],
            "issues": [],
            "investigation_trace": [],
        },
    },
    "issues": [
        {
            "severity": "high",
            "category": "security",
            "title": "Shell",
            "file": "a.py",
            "line": None,
            "recommendation": "fix",
            "occurrences": 2,
            "description": "d",
            "source": "bandit",
            "rule_id": "B602",
            "locations": [{"file": "a.py", "line": None}],
        }
    ],
    "quick_wins": [],
    "collector_status": {"security": {"status": "ok", "detail": None}},
    "investigation_plan": {},
}


@pytest.fixture
def fake_service(monkeypatch):
    service = MagicMock()
    service.return_value.analyze.return_value = REPORT
    monkeypatch.setattr("drrepo.service.AnalysisService", service)
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config(groq_api_key="k"))
    return service


def test_analyze_prints_summary_and_writes_reports(fake_service, tmp_path, capsys):
    code = cli.main(
        [
            "https://github.com/octo/demo",
            "-o",
            str(tmp_path),
            "--format",
            "json,sarif",
            "--log-file",
            "",
        ]
    )
    out = capsys.readouterr()
    assert code == 0
    assert "DrRepo report: octo/demo" in out.out and "[deep]" in out.out and "n/a" in out.out
    assert "(a.py)" in out.out  # no ":None"
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".sarif"]


def test_json_output_and_fail_under(fake_service, capsys):
    code = cli.main(
        [
            "analyze",
            "https://github.com/octo/demo",
            "--json",
            "--format",
            "",
            "--fail-under",
            "50",
            "--log-file",
            "",
        ]
    )
    assert code == cli.EXIT_FAIL_UNDER
    assert json.loads(capsys.readouterr().out)["overall_score"] == 42.0


def test_shallow_flag_propagates(fake_service):
    cli.main(
        [
            "analyze",
            "https://github.com/octo/demo",
            "--shallow",
            "--no-history",
            "--format",
            "",
            "-q",
            "--log-file",
            "",
        ]
    )
    config = fake_service.call_args.args[0]
    assert config.enable_deep_investigation is False and config.enable_score_history is False


def test_bad_format_and_bad_url(fake_service, capsys):
    assert (
        cli.main(["analyze", "https://github.com/a/b", "--format", "pdf", "--log-file", ""])
        == cli.EXIT_USAGE
    )
    fake_service.return_value.analyze.side_effect = ValueError("Only GitHub")
    assert (
        cli.main(["analyze", "https://x.com/a/b", "--format", "", "--log-file", ""])
        == cli.EXIT_USAGE
    )
    assert "Only GitHub" in capsys.readouterr().err


def test_configuration_error_exit_code(monkeypatch, capsys):
    from drrepo.errors import ConfigurationError

    def bad(_e):
        raise ConfigurationError("MODEL_PROVIDER='x' is not supported")

    monkeypatch.setattr(cli, "_load_config", bad)
    assert cli.main(["health"]) == cli.EXIT_USAGE
    assert "not supported" in capsys.readouterr().err


def test_health_command(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config())
    monkeypatch.setattr(
        "drrepo.interfaces.health.check_all",
        lambda _c: {
            "status": "degraded",
            "version": "x",
            "components": {
                "github_api": {"status": "degraded", "latency_ms": 5, "detail": "unauthenticated"}
            },
        },
    )
    assert cli.main(["health"]) == 0
    assert "github_api" in capsys.readouterr().out


def test_ui_builds_streamlit_command(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    assert cli.main(["ui", "--port", "9000", "--headless"]) == 0
    cmd = calls[0]
    assert cmd[1:4] == ["-m", "streamlit", "run"] and cmd[4].endswith("streamlit_app.py")
    assert "--server.port=9000" in cmd and "--server.headless=true" in cmd


def test_doctor_offline(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config(groq_api_key="k", github_token="t"))
    code = cli.main(["doctor", "--offline"])
    out = capsys.readouterr().out
    assert "[ OK ] Python" in out and "configuration" in out
    assert code in (0, 1)  # depends on whether git is installed on the test host


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.startswith("drrepo ")


def test_mcp_command_forwards_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config())
    monkeypatch.setattr("drrepo.interfaces.mcp_server.run", lambda **kwargs: calls.append(kwargs))
    argv = ["mcp", "--transport", "streamable-http", "--port", "9001", "--log-file", ""]
    assert cli.main(argv) == cli.EXIT_OK
    assert calls == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 9001}]


def test_health_api_command_starts_uvicorn(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config())
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    assert cli.main(["health-api", "--port", "8001", "--log-file", ""]) == cli.EXIT_OK
    app, kwargs = calls[0]
    assert app == "drrepo.interfaces.health:app" and kwargs["port"] == 8001


def test_doctor_reports_missing_semgrep_with_install_hint(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config())
    monkeypatch.setattr(
        "drrepo.recon.scanners.find_executable",
        lambda name: None if name == "semgrep" else f"/bin/{name}",
    )
    cli.main(["doctor", "--offline"])
    out = capsys.readouterr().out
    assert "[WARN] semgrep" in out and "uv tool install semgrep" in out


def test_unexpected_error_and_interrupt_exit_codes(monkeypatch, capsys):
    def boom(_e):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "_load_config", boom)
    assert cli.main(["health"]) == cli.EXIT_ERROR
    assert "RuntimeError: kaboom" in capsys.readouterr().err

    def interrupt(_e):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_load_config", interrupt)
    assert cli.main(["health"]) == 130
