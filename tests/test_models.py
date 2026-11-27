import pytest

from drrepo.models import (
    Category,
    CategoryFinding,
    InvestigationDepth,
    InvestigationPlan,
    Issue,
    Location,
    Report,
    Severity,
    ToolCallTrace,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HIGH", Severity.HIGH),
        ("Moderate", Severity.MEDIUM),
        ("ERROR", Severity.HIGH),
        ("info", Severity.LOW),
        ("urgent", Severity.MEDIUM),
        (None, Severity.MEDIUM),
    ],
)
def test_severity_parse(raw, expected):
    assert Severity.parse(raw) == expected


def test_severity_parse_custom_default_and_rank():
    assert Severity.parse("???", default=Severity.HIGH) == Severity.HIGH
    assert [s.rank for s in Severity] == [0, 1, 2, 3]


def test_issue_roundtrip_and_primary_location():
    issue = Issue(
        severity=Severity.HIGH,
        category=Category.SECURITY,
        title="t",
        description="d",
        recommendation="r",
        source="bandit",
        rule_id="B602",
        locations=[Location("a.py", 3), Location("b.py", 9)],
        occurrences=2,
    )
    assert (issue.file, issue.line) == ("a.py", 3)
    assert Issue.from_dict(issue.to_dict()) == issue


def test_issue_from_legacy_dict_with_file_only():
    issue = Issue.from_dict(
        {
            "severity": "low",
            "category": "documentation",
            "title": "x",
            "file": "README.md",
            "line": None,
        }
    )
    assert issue.locations == [Location("README.md", None)]
    assert issue.source == "documentation"


def test_category_finding_roundtrip():
    finding = CategoryFinding(
        category=Category.CODE_QUALITY,
        score=81.26,
        summary="s",
        assessed=False,
        investigation_depth=InvestigationDepth.DEEP,
        investigation_trace=[ToolCallTrace("read_file", {"path": "a"}, "obs")],
        notes=["n"],
    )
    restored = CategoryFinding.from_dict(finding.to_dict())
    assert restored.score == 81.3
    assert restored.assessed is False
    assert restored.investigation_trace == finding.investigation_trace


def test_plan_helpers():
    plan = InvestigationPlan.all_shallow("why")
    assert plan.deep_categories() == []
    assert plan.to_dict()["security"] == {"depth": "shallow", "rationale": "why"}


def test_report_issue_counts():
    report = Report(
        repository={},
        overall_score=50,
        category_scores={},
        issues=[Issue(Severity.LOW, Category.SECURITY, "a", "", "", "x")] * 2,
        quick_wins=[],
        collector_status={},
    )
    assert report.to_dict()["issue_counts"] == {"critical": 0, "high": 0, "medium": 0, "low": 2}
