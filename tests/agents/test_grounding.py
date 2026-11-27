"""Agent findings are verified against the clone and the agent's own tool trace."""

import pytest

from drrepo.agents.grounding import UNVERIFIED_MARK, examined_paths, ground_issues
from drrepo.models import Category, Issue, Location, Severity, ToolCallTrace

SOURCE = "import os\n\n\ndef run(cmd):\n    os.system(cmd)  # shell injection\n    return True\n"


@pytest.fixture
def root(make_repo):
    return make_repo({"app/run.py": SOURCE, "docs/guide.md": "# Guide\n"})


def _issue(file=None, line=None, severity=Severity.HIGH, title="Shell injection"):
    locations = [Location(file, line)] if file else []
    return Issue(
        severity,
        Category.SECURITY,
        title,
        "desc",
        "fix",
        "investigator:security",
        locations=locations,
    )


def _read(path):
    return ToolCallTrace("read_file", {"path": path}, "    1| import os")


def test_verified_finding_passes_unchanged(root):
    issue = _issue("app/run.py", 5)
    result = ground_issues([issue], clone_root=str(root), trace=[_read("app/run.py")])
    assert result.kept == [issue] and not result.downgraded and not result.dropped
    assert result.note() is None


@pytest.mark.parametrize(
    ("file", "line", "reason"),
    [
        ("app/missing.py", 1, "does not exist"),
        ("app/run.py", 99, "outside app/run.py"),
        ("../etc/passwd", 1, "outside the repository"),
        ("app", None, "does not exist"),  # a directory, not a file
    ],
)
def test_fabricated_citations_are_dropped(root, file, line, reason):
    result = ground_issues([_issue(file, line)], clone_root=str(root), trace=[_read(file)])
    assert result.kept == []
    assert reason in result.dropped[0][1]
    assert "dropped 1" in (result.note() or "")


def test_unread_file_is_capped_at_low_and_marked(root):
    result = ground_issues([_issue("app/run.py", 5)], clone_root=str(root), trace=[])
    [kept] = result.kept
    assert kept.severity is Severity.LOW
    assert kept.title.startswith(UNVERIFIED_MARK)
    assert "never opened or searched app/run.py" in kept.description


def test_no_file_cited_is_capped_at_low(root):
    [kept] = ground_issues([_issue()], clone_root=str(root), trace=[]).kept
    assert kept.severity is Severity.LOW and "cites no file" in kept.description


def test_low_findings_keep_their_severity_when_downgraded(root):
    [kept] = ground_issues([_issue(severity=Severity.LOW)], clone_root=str(root), trace=[]).kept
    assert kept.severity is Severity.LOW


def test_quoted_evidence_must_be_in_the_file_near_the_line(root):
    trace = [_read("app/run.py")]
    good = ground_issues(
        [_issue("app/run.py", 5)], clone_root=str(root), trace=trace, evidence={0: "os.system(cmd)"}
    )
    assert good.kept[0].severity is Severity.HIGH
    bad = ground_issues(
        [_issue("app/run.py", 5)],
        clone_root=str(root),
        trace=trace,
        evidence={0: "eval(user_input)"},
    )
    assert (
        bad.kept[0].severity is Severity.LOW and "evidence was not found" in bad.kept[0].description
    )


def test_search_results_and_scanner_runs_count_as_examined(root):
    search = ToolCallTrace("search_code", {"pattern": "os.system"}, "app/run.py:5: os.system(cmd)")
    scan_all = ToolCallTrace("run_scanner_on_path", {"scanner": "bandit", "path": "."}, "")
    listing = ToolCallTrace("list_directory", {"path": "app"}, "file  app/run.py  (80 bytes)")
    assert "app/run.py" in examined_paths([search]).files
    assert (
        ground_issues([_issue("app/run.py", 5)], clone_root=str(root), trace=[scan_all])
        .kept[0]
        .severity
        is Severity.HIGH
    )
    # Listing a directory shows names, not contents: not enough to verify a claim.
    listed = ground_issues([_issue("app/run.py", 5)], clone_root=str(root), trace=[listing])
    assert listed.kept[0].severity is Severity.LOW
