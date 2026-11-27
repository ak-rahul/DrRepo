import pytest

from drrepo.models import (
    Category,
    CategoryFinding,
    CollectorResult,
    CollectorStatus,
    InvestigationDepth,
    InvestigationPlan,
    Issue,
    Location,
    RepoRef,
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


def test_issue_primary_location_and_dict():
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
    d = issue.to_dict()
    assert d["file"] == "a.py" and d["locations"][1] == {"file": "b.py", "line": 9}
    assert d["severity"] == "high" and d["occurrences"] == 2
    assert Issue(Severity.LOW, Category.SECURITY, "x", "", "", "s").file is None


def test_category_finding_dict_rounds_score():
    finding = CategoryFinding(
        category=Category.CODE_QUALITY,
        score=81.26,
        summary="s",
        assessed=False,
        investigation_depth=InvestigationDepth.DEEP,
        investigation_trace=[ToolCallTrace("read_file", {"path": "a"}, "obs")],
        notes=["n"],
    )
    d = finding.to_dict()
    assert d["score"] == 81.3 and d["assessed"] is False and d["investigation_depth"] == "deep"
    assert d["investigation_trace"] == [
        {"tool": "read_file", "tool_input": {"path": "a"}, "observation": "obs"}
    ]


def test_plan_helpers():
    plan = InvestigationPlan.all_shallow("why")
    assert all(plan.depth_for(c) == InvestigationDepth.SHALLOW for c in Category)
    assert plan.to_dict()["security"] == {"depth": "shallow", "rationale": "why"}


def test_collector_result_helpers():
    assert CollectorResult("x", CollectorStatus.OK).ok
    skipped = CollectorResult.skipped("x", "no clone")
    assert not skipped.ok and skipped.to_dict() == {
        "status": "skipped",
        "data": {},
        "detail": "no clone",
    }


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


# ------------------------------------------------------------ RepoRef ---


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/demo",
        "https://github.com/octo/demo/",
        "https://github.com/octo/demo.git",
        "https://github.com/octo/demo/tree/main/src",
        "http://www.github.com/octo/demo",
        "github.com/octo/demo",
        "  https://github.com/octo/demo  ",
    ],
)
def test_accepts_common_forms(url):
    assert RepoRef.parse(url) == RepoRef("octo", "demo")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://gitlab.com/octo/demo",
        "https://github.com/octo",
        "ftp://github.com/octo/demo",
        "https://user:pass@github.com/octo/demo",
        "https://github.com/-bad/demo",
        "https://github.com/octo/..",
        "https://github.com.evil.com/octo/demo",
    ],
)
def test_rejects_invalid(url):
    with pytest.raises(ValueError):
        RepoRef.parse(url)


def test_derived_urls():
    ref = RepoRef("octo", "demo")
    assert ref.full_name == "octo/demo"
    assert ref.html_url == "https://github.com/octo/demo"
    assert ref.clone_url == "https://github.com/octo/demo.git"
