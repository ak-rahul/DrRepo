"""Shared fixtures for the report package: a small but realistic synthesized report."""

from unittest.mock import MagicMock, patch

import pytest

from drrepo.models import (
    Category,
    CategoryFinding,
    InvestigationPlan,
    Issue,
    Location,
    Severity,
    ToolCallTrace,
)
from drrepo.report.synthesis import synthesize_report
from tests.conftest import ok


def _finding(category, score, assessed=True, issues=None, trace=None):
    return CategoryFinding(
        category=category,
        score=score,
        summary=f"{category.value} | summary",
        issues=issues or [],
        assessed=assessed,
        investigation_trace=trace or [],
    )


def _issue(
    sev, title, rec="fix it", category=Category.SECURITY, locations=None, source="bandit", rule="B1"
):
    return Issue(sev, category, title, "desc", rec, source, rule_id=rule, locations=locations or [])


@pytest.fixture
def report_dict():
    findings = {
        "security": _finding(
            Category.SECURITY,
            40,
            issues=[
                _issue(
                    Severity.HIGH, "Shell", locations=[Location("a.py", 3), Location("b.py", None)]
                ),
                _issue(Severity.LOW, "Weak", rec="tweak"),
            ],
            trace=[ToolCallTrace("read_file", {"path": "a.py"}, "obs")],
        ),
        "documentation": _finding(
            Category.DOCUMENTATION,
            80,
            issues=[
                _issue(
                    Severity.MEDIUM,
                    "No usage",
                    category=Category.DOCUMENTATION,
                    source="readme_analyzer",
                    rule=None,
                )
            ],
        ),
        "code_quality": _finding(Category.CODE_QUALITY, 0, assessed=False),
    }
    report = synthesize_report(
        repository={
            "name": "demo",
            "full_name": "octo/demo",
            "url": "https://github.com/octo/demo",
        },
        category_findings=findings,
        collector_status={"security": {"status": "ok", "detail": None}},
        investigation_plan=InvestigationPlan.all_shallow("test"),
        generated_at="2026-11-27T00:00:00+00:00",
        drrepo_version="9.9.9",
    )
    return report.to_dict()


@pytest.fixture
def pipeline(tmp_path, github_data):
    """Patch clone + every collector with one bandit finding; yields the fake clone dir."""
    clone = tmp_path / "clone"
    clone.mkdir()
    cloned = MagicMock(path=clone)
    finding = {
        "tool": "bandit",
        "rule": "B605",
        "message": "shell",
        "severity": "HIGH",
        "file": "src/pager.py",
        "line": 3,
    }
    results = {
        "clone_repo": (cloned, ok(name="repo_clone")),
        "collect_github_metadata": ok(github_data),
        "collect_repo_layout": ok({"file_structure": {"has_tests": True}}),
        "collect_static_analysis": ok({"findings": []}),
        "collect_security": ok({"findings": [finding], "tool_status": {"bandit": "ok"}}),
        "collect_dependency_audit": ok({"vulnerabilities": [], "manifests": [], "unpinned": []}),
        "collect_infrastructure": ok({"findings": [], "tool_status": {}}),
    }
    patches = [patch(f"drrepo.pipeline.{n}", return_value=r) for n, r in results.items()]
    for p in patches:
        p.start()
    yield clone
    for p in patches:
        p.stop()
