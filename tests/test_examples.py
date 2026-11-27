"""The scripts in examples/ import cleanly and their own logic works (hermetic)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from drrepo.agents.analysts.base import Assessment
from drrepo.agents.analysts.maintainability import MaintainabilityAnalyst
from drrepo.models import CollectorStatus
from tests.conftest import ok

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"examples_{name}", EXAMPLES / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.py")), ids=lambda p: p.name)
def test_every_example_imports_and_has_main(path):
    module = load(path.stem)
    assert callable(module.main)
    assert module.__doc__ and "uv run python examples/" in module.__doc__


def _report(**overrides):
    report = {
        "overall_score": 80.0,
        "category_scores": {"security": {"score": 90.0, "assessed": True}},
        "issues": [],
    }
    report.update(overrides)
    return report


def test_policy_gate_passes_clean_report():
    gate = load("policy_gate")
    assert gate.violations(_report(), min_score=60, min_category=40) == []


def test_policy_gate_flags_score_category_and_blocking_issues():
    gate = load("policy_gate")
    issues = [
        {"severity": "high", "category": "security", "title": "Shell", "file": "a.py", "line": 3},
        {"severity": "critical", "category": "dependencies", "title": "CVE", "file": None},
        {"severity": "high", "category": "documentation", "title": "Docs", "file": "README.md"},
    ]
    report = _report(
        overall_score=50.0,
        category_scores={
            "security": {"score": 20.0, "assessed": True},
            "dependencies": {"score": 0.0, "assessed": False},  # unassessed: ignored
        },
        issues=issues,
    )
    assert gate.violations(report, min_score=60, min_category=40) == [
        "overall score 50.0 < 60",
        "security score 20.0 < 40",
        "high security: Shell at a.py:3",
        "critical dependencies: CVE",
    ]


def test_custom_collector_counts_markers_in_source_only(make_repo):
    example = load("custom_collector")
    root = make_repo(
        {
            "pkg/a.py": "x = 1  # TODO: fix\n# FIXME later\nprint('TODO in a string')\n",
            "web/app.js": "// HACK around a bug\n",
            "notes.md": "TODO: not source\n",
        }
    )
    result = example.collect_todo_markers(str(root))
    assert result.status == CollectorStatus.OK
    assert result.data["by_marker"] == {"TODO": 1, "FIXME": 1, "HACK": 1}
    assert {"file": "pkg/a.py", "line": 1, "marker": "TODO"} in result.data["samples"]


def test_custom_analyst_adds_issue_only_above_density_limit(monkeypatch):
    example = load("custom_collector")
    monkeypatch.setattr(
        MaintainabilityAnalyst,
        "assess",
        lambda self, recon: Assessment(issues=[], score=90.0, summary="s"),
    )
    analyst = example.TodoAwareMaintainabilityAnalyst()

    def recon(total):
        data = {"total": total, "lines_scanned": 1000, "by_marker": {"TODO": total}, "samples": []}
        return {"todo_markers": ok(data, name="todo_markers")}

    assert analyst.assess(recon(2)).issues == []
    dense = analyst.assess(recon(40))
    assert [i.source for i in dense.issues] == ["todo_markers"]
    assert dense.score < 90.0


def test_custom_collector_wires_into_the_graph():
    example = load("custom_collector")
    from drrepo.config import Config

    service = example.build_service(Config())
    assert "todo_markers" in service.workflow.graph.nodes
