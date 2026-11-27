import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from drrepo.collectors import scanners
from drrepo.collectors.scanners import run_bandit, run_ruff, run_semgrep
from drrepo.collectors.security import collect_security, scan_secrets
from drrepo.collectors.static_analysis import collect_static_analysis
from drrepo.config import Config


@pytest.fixture
def fake_run(monkeypatch):
    """Replace subprocess.run in the scanner module; records argv and returns canned stdout."""
    calls: list[dict] = []
    outputs: dict[str, str] = {}

    def run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        tool = Path(argv[0]).stem
        return SimpleNamespace(stdout=outputs.get(tool, ""), stderr="", returncode=0)

    monkeypatch.setattr(scanners, "find_executable", lambda name: f"/bin/{name}")
    monkeypatch.setattr(scanners.subprocess, "run", run)
    return SimpleNamespace(calls=calls, outputs=outputs)


def test_ruff_isolated_and_relative_paths(tmp_path, fake_run):
    fake_run.outputs["ruff"] = json.dumps(
        [
            {
                "code": "F821",
                "message": "Undefined name `x`",
                "filename": str(tmp_path / "pkg" / "a.py"),
                "location": {"row": 3},
                "url": "https://docs/F821",
            }
        ]
    )
    result = run_ruff(tmp_path)
    assert result.available
    assert result.findings == [
        {
            "tool": "ruff",
            "rule": "F821",
            "message": "Undefined name `x`",
            "severity": None,
            "file": "pkg/a.py",
            "line": 3,
            "url": "https://docs/F821",
        }
    ]
    call = fake_run.calls[0]
    assert "--isolated" in call["argv"] and call["cwd"] == tmp_path
    assert call["stdin"] is subprocess.DEVNULL


def test_bandit_skips_asserts_and_excludes_tests(tmp_path, fake_run):
    fake_run.outputs["bandit"] = json.dumps(
        {
            "results": [
                {
                    "test_id": "B602",
                    "issue_text": "shell",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "filename": "./app/run.py",
                    "line_number": 8,
                }
            ]
        }
    )
    result = run_bandit(tmp_path)
    assert result.findings[0]["file"] == "app/run.py"
    argv = fake_run.calls[0]["argv"]
    assert argv[argv.index("--skip") + 1] == "B101"
    assert "*/tests/*" in argv[argv.index("-x") + 1]


def test_semgrep_metrics_off(tmp_path, fake_run):
    fake_run.outputs["semgrep"] = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.x.y",
                    "path": "a.py",
                    "start": {"line": 1},
                    "extra": {"message": "m", "severity": "ERROR"},
                }
            ]
        }
    )
    result = run_semgrep(tmp_path)
    assert result.findings[0]["rule"] == "python.x.y"
    assert "--metrics=off" in fake_run.calls[0]["argv"]


def test_unparseable_output_is_unavailable(tmp_path, fake_run):
    fake_run.outputs["ruff"] = "not json"
    result = run_ruff(tmp_path)
    assert not result.available and "unparseable" in result.reason


def test_missing_tool_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(scanners, "find_executable", lambda name: None)
    assert run_ruff(tmp_path).reason == "ruff not installed"

    monkeypatch.setattr(scanners, "find_executable", lambda name: "/bin/x")

    def timeout(*_a, **_k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(scanners.subprocess, "run", timeout)
    assert "timed out" in run_bandit(tmp_path, timeout=1).reason


AWS_KEY = "AKIA" + "Q3RZ7XK2M9PLW4TB"
GH_TOKEN = "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hJ6"


def test_secret_scan_finds_real_looking_secrets_only(make_repo):
    root = make_repo(
        {
            "config.py": f'AWS = "{AWS_KEY}"\napi_key = "your_api_key_here_please"\n',
            "deploy/key.pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n",
            "tests/certs/server.key": "-----BEGIN PRIVATE KEY-----\nabc\n",
            "app.js": f"const t = '{GH_TOKEN}';",
            "settings.py": 'password = "Zx8#kQ2!vB9mW4pL"\n',  # chars outside the generic charset
            "secret = 'aaaaaaaaaaaaaaaaaaaa'.py": "",
            "node_modules/pkg/leak.js": f"'{AWS_KEY}'",
            "img.png": b"\x89PNG\x00" + AWS_KEY.encode(),
        }
    )
    findings = scan_secrets(root)
    found = {(f["file"], f["rule"], f["severity"]) for f in findings}
    assert found == {
        ("config.py", "AWS Access Key", "CRITICAL"),
        ("deploy/key.pem", "Private Key Block", "CRITICAL"),
        ("app.js", "GitHub Token", "CRITICAL"),
        ("tests/certs/server.key", "Private Key Block", "LOW"),  # test fixture
    }
    assert all(AWS_KEY not in json.dumps(f) for f in findings)  # never echo the secret


def test_generic_assignment_needs_entropy(make_repo):
    root = make_repo(
        {"a.py": 'client_secret = "Q7v9XkP2mL4nR8sT6wY1zB3c"\ntoken = "aaaaaaaaaaaaaaaaaaaa"\n'}
    )
    findings = scan_secrets(root)
    assert [(f["line"], f["severity"]) for f in findings] == [(1, "HIGH")]


def test_collect_security_combines_and_reports_tool_status(make_repo, monkeypatch):
    root = make_repo({"a.py": f'k = "{AWS_KEY}"'})
    monkeypatch.setattr(
        "drrepo.collectors.security.run_bandit",
        lambda *_a, **_k: scanners.ScanResult("bandit", True, [{"tool": "bandit", "rule": "B602"}]),
    )
    monkeypatch.setattr(
        "drrepo.collectors.security.run_semgrep",
        lambda *_a, **_k: scanners.ScanResult("semgrep", False, reason="semgrep not installed"),
    )
    result = collect_security(str(root), Config())
    assert result.data["tool_status"] == {
        "bandit": "ok",
        "semgrep": "skipped: semgrep not installed",
        "secret_scan": "ok",
    }
    assert {f["tool"] for f in result.data["findings"]} == {"bandit", "secret_scan"}


def test_collect_security_respects_toggles(make_repo):
    root = make_repo({"a.py": "x = 1"})
    result = collect_security(str(root), Config(enable_bandit=False, enable_semgrep=False))
    assert result.data["tool_status"]["bandit"] == "disabled by config"
    assert result.status.value == "ok"  # secret scan still ran


def test_static_analysis_skipped_when_ruff_missing(make_repo, monkeypatch):
    root = make_repo({"a.py": "x"})
    monkeypatch.setattr(
        "drrepo.collectors.static_analysis.run_ruff",
        lambda *_a, **_k: scanners.ScanResult("ruff", False, reason="ruff not installed"),
    )
    result = collect_static_analysis(str(root), Config())
    assert result.status.value == "skipped"
    assert result.data["tool_status"]["ruff"].startswith("skipped")


@pytest.mark.skipif(scanners.find_executable("ruff") is None, reason="ruff not installed")
def test_real_ruff_on_real_file(make_repo):
    root = make_repo({"bad.py": "def f():\n    return undefined_name\n"})
    result = run_ruff(root)
    assert result.available
    assert [(f["rule"], f["file"], f["line"]) for f in result.findings] == [("F821", "bad.py", 2)]
