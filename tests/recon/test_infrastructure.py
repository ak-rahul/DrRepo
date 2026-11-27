"""CI workflow and Dockerfile audits (zizmor, hadolint, root-user check)."""

import pytest

from drrepo.agents.analysts.maintainability import MaintainabilityAnalyst
from drrepo.agents.analysts.security import SecurityAnalyst
from drrepo.config import Config
from drrepo.recon import infrastructure
from drrepo.recon.infrastructure import check_dockerfile_user, collect_infrastructure, is_dockerfile
from drrepo.recon.scanners import find_executable
from tests.conftest import ok

DANGEROUS_WORKFLOW = """name: pr
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: echo "${{ github.event.pull_request.title }}"
"""
ROOT_DOCKERFILE = (
    "FROM python:latest\nARG API_TOKEN=abc123\nRUN pip install flask\nCMD python app.py\n"
)
SAFE_DOCKERFILE = 'FROM python:3.12-slim\nUSER 1000:1000\nCMD ["python", "app.py"]\n'

needs_tools = pytest.mark.skipif(
    not (find_executable("zizmor") and find_executable("hadolint")),
    reason="zizmor/hadolint not installed",
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Dockerfile", True),
        ("dockerfile", True),
        ("Dockerfile.prod", True),
        ("api.Dockerfile", True),
        ("docker-compose.yml", False),
        ("Dockerfiles.md", False),
    ],
)
def test_dockerfile_detection(name, expected):
    assert is_dockerfile(name) is expected


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        (ROOT_DOCKERFILE, True),
        (SAFE_DOCKERFILE, False),
        ("FROM a AS build\nUSER app\nFROM b\nCMD x\n", True),  # only the final stage counts
        ("FROM a\nUSER app\nUSER root\n", True),
        ("FROM a\nUSER 0:0\n", True),
        ("# no instructions\n", False),
    ],
)
def test_root_user_check_looks_at_the_final_stage(make_repo, text, flagged):
    root = make_repo({"Dockerfile": text})
    assert (check_dockerfile_user(root, root / "Dockerfile") is not None) is flagged


@needs_tools
def test_real_tools_find_workflow_and_container_problems(make_repo):
    root = make_repo(
        {
            ".github/workflows/pr.yml": DANGEROUS_WORKFLOW,
            "Dockerfile": ROOT_DOCKERFILE,
            # A repo-level config and an inline ignore must not silence anything.
            "zizmor.yml": "rules:\n  template-injection:\n    disable: true\n",
            ".hadolint.yaml": "ignored: [DL3007, DL3064]\n",
        }
    )
    result = collect_infrastructure(str(root), Config())
    assert result.data["tool_status"] == {
        "zizmor": "ok",
        "hadolint": "ok",
        "dockerfile_checks": "ok",
    }
    found = {(f["tool"], f["rule"]): f for f in result.data["findings"]}
    injection = found[("zizmor", "template-injection")]
    assert (injection["severity"], injection["file"], injection["line"]) == (
        "high",
        ".github/workflows/pr.yml",
        10,
    )
    assert ("zizmor", "dangerous-triggers") in found
    assert found[("hadolint", "DL3007")]["category"] == "maintainability"
    secret_arg = found[("hadolint", "DL3064")]
    assert (secret_arg["category"], secret_arg["severity"]) == ("security", "medium")
    assert found[("drrepo", "container-runs-as-root")]["category"] == "security"


def test_toggles_and_missing_inputs(make_repo):
    root = make_repo({"Dockerfile": SAFE_DOCKERFILE})
    disabled = collect_infrastructure(
        str(root), Config(enable_workflow_audit=False, enable_dockerfile_audit=False)
    )
    assert set(disabled.data["tool_status"].values()) == {"disabled by config"}


def test_repo_without_workflows_or_dockerfiles(make_repo):
    empty = collect_infrastructure(str(make_repo({"a.py": "x = 1"})), Config())
    assert empty.data["tool_status"]["zizmor"] == "skipped: no GitHub Actions workflows"
    assert empty.data["tool_status"]["hadolint"] == "skipped: no Dockerfiles"


def test_missing_tool_is_skipped_not_fatal(make_repo, monkeypatch):
    monkeypatch.setattr(infrastructure, "find_executable", lambda _name: None)
    root = make_repo(
        {".github/workflows/ci.yml": DANGEROUS_WORKFLOW, "Dockerfile": ROOT_DOCKERFILE}
    )
    result = collect_infrastructure(str(root), Config())
    assert result.data["tool_status"]["zizmor"] == "skipped: zizmor not installed"
    # The built-in root-user check needs no external tool.
    assert [f["rule"] for f in result.data["findings"]] == ["container-runs-as-root"]


def test_analysts_route_findings_by_category():
    findings = [
        {
            "tool": "zizmor",
            "rule": "template-injection",
            "message": "m",
            "severity": "high",
            "file": ".github/workflows/pr.yml",
            "line": 10,
            "category": "security",
        },
        {
            "tool": "hadolint",
            "rule": "DL3007",
            "message": "latest",
            "severity": "low",
            "file": "Dockerfile",
            "line": 1,
            "category": "maintainability",
        },
    ]
    recon = {
        "security": ok({"findings": [], "tool_status": {"bandit": "ok"}}, name="security"),
        "infrastructure": ok(
            {"findings": findings, "tool_status": {"zizmor": "ok", "hadolint": "ok"}},
            name="infrastructure",
        ),
        "repo_layout": ok({"file_structure": {"has_tests": True}}, name="repo_layout"),
    }
    security = SecurityAnalyst().assess(recon)
    assert [i.source for i in security.issues] == ["zizmor"]
    assert security.score < 100
    maintainability = MaintainabilityAnalyst().assess(recon)
    assert "hadolint" in {i.source for i in maintainability.issues}
