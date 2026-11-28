"""Pure view helpers behind the Streamlit UI."""

import pytest

from drrepo.interfaces import ui_data as ui


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("![x](https://evil.example/p.png)", r"\!\[x\]\(https://evil.example/p.png\)"),
        ("<img src=x onerror=alert(1)>", r"\<img src=x onerror=alert\(1\)\>"),
        ("costs $5 and $6", r"costs \$5 and \$6"),
        ("*bold* _it_ `code`", r"\*bold\* \_it\_ \`code\`"),
        ("# Heading", r"\# Heading"),
        ("- item\n1. first\n---", "\\- item\n1\\. first\n\\---"),
        ("README.md in a-b/c, v1.2", "README.md in a-b/c, v1.2"),  # ordinary text untouched
        (None, ""),
    ],
)
def test_escape_markdown(raw, escaped):
    assert ui.escape_markdown(raw) == escaped


def _issue(title, severity="high", category="security", source="bandit", file="a.py", rule="B1"):
    return {
        "title": title,
        "severity": severity,
        "category": category,
        "source": source,
        "rule_id": rule,
        "file": file,
        "line": 3,
        "occurrences": 1,
    }


ISSUES = [
    _issue("Shell injection"),
    _issue("Weak hash", severity="low", rule="B303"),
    _issue("[disputed] Token leak", source="investigator:security", rule="agent-finding"),
    _issue("No usage", category="documentation", source="readme_analyzer", file="README.md"),
]


def test_filter_issues():
    titles = lambda issues: [i["title"] for i in issues]  # noqa: E731
    assert titles(ui.filter_issues(ISSUES, severities=["low"])) == ["Weak hash"]
    assert titles(ui.filter_issues(ISSUES, origin="Agents")) == ["[disputed] Token leak"]
    assert len(ui.filter_issues(ISSUES, origin="Scanners and checks")) == 3
    assert "[disputed] Token leak" not in titles(ui.filter_issues(ISSUES, hide_marked=True))
    assert titles(ui.filter_issues(ISSUES, query="readme")) == ["No usage"]  # file match
    assert titles(ui.filter_issues(ISSUES, query="B303")) == ["Weak hash"]  # rule match
    assert titles(ui.filter_issues(ISSUES, sources=["readme_analyzer"])) == ["No usage"]
    assert ui.filter_issues(ISSUES, categories=[]) == []


def test_issue_heading_is_escaped_and_counts_once():
    heading = ui.issue_heading(dict(_issue("Use `eval`"), occurrences=3))
    assert heading == r"🟠 Use \`eval\` ×3 — a.py:3"
    counted = ui.issue_heading(dict(_issue("bandit B603 (8 occurrences)"), occurrences=8))
    assert "×8" not in counted


def test_page():
    assert ui.page(list(range(120)), 3, 50) == (list(range(100, 120)), 3)
    assert ui.page(list(range(10)), 9, 50) == (list(range(10)), 1)  # clamped
    assert ui.page([], 1, 50) == ([], 1)


REPORT = {
    "dependencies": [
        {
            "ecosystem": "PyPI",
            "name": "jinja2",
            "version": "3.1.2",
            "scope": "runtime",
            "license": "BSD-3-Clause",
            "vulnerabilities": ["GHSA-1", "GHSA-2"],
        },
        {
            "ecosystem": "PyPI",
            "name": "pytest",
            "version": "8.0",
            "scope": "dev",
            "license": None,
            "vulnerabilities": [],
        },
        {
            "ecosystem": "npm",
            "name": "left-pad",
            "version": "1.0.0",
            "scope": "runtime",
            "license": None,
            "vulnerabilities": [],
        },
    ],
    "llm_usage": {"by_label": {"planner": 100, "investigation:security": 300}},
    "suppressed": [
        {
            "issue": _issue("Shell"),
            "suppression": {
                "rule": "bandit/B1",
                "path": None,
                "reason": "by design",
                "expires": None,
                "origin": "local",
            },
        }
    ],
    "provenance": {
        "llm": {"provider": "groq", "model": "m", "roles": {"planner": "m", "critic": "c"}},
        "tools": {"ruff": "0.1", "semgrep": None},
        "instructions": {"planner": "abc"},
    },
}


def test_tables():
    rows = ui.dependency_rows(REPORT)
    assert rows[0]["package"] == "jinja2" and rows[0]["advisories"] == 2  # vulnerable first
    assert [r["package"] for r in ui.dependency_rows(REPORT, vulnerable_only=True)] == ["jinja2"]
    assert ui.license_counts(REPORT) == {"unknown": 1, "BSD-3-Clause": 1}  # runtime only
    assert ui.usage_rows(REPORT)[0] == {
        "step": "investigation:security",
        "tokens": 300,
        "share": "75%",
    }
    assert ui.suppressed_rows(REPORT)[0]["reason"] == "by design"
    tables = ui.provenance_rows(REPORT)
    assert {r["role"] for r in tables["models"]} == {"planner", "critic"}
    assert {"tool": "semgrep", "version": "not installed"} in tables["tools"]
    assert ui.usage_rows({}) == [] and ui.provenance_rows({})["models"] == []


def test_history_and_diff_rows():
    runs = [
        {"timestamp": "2026-11-01T10:00:00+00:00", "overall_score": 70.0},
        {"timestamp": None, "overall_score": 1.0},
        {"timestamp": "2026-11-02T10:00:00+00:00", "overall_score": 72.5},
    ]
    assert ui.history_points(runs) == [
        {"run": "2026-11-01 10:00", "overall": 70.0},
        {"run": "2026-11-02 10:00", "overall": 72.5},
    ]
    diff = {"category_deltas": {"code_quality": {"base": 90.0, "head": 80.0, "delta": -10.0}}}
    assert ui.category_delta_rows(diff) == [
        {"category": "Code Quality", "base": 90.0, "head": 80.0, "change": -10.0}
    ]


def test_evidence_steps_are_the_calls_that_touched_the_cited_file():
    trace = [
        {"tool": "list_directory", "tool_input": {"path": "."}, "observation": "app.py\nlib.py"},
        {"tool": "read_file", "tool_input": {"path": "app.py"}, "observation": "DEBUG = True"},
        {"tool": "read_file", "tool_input": {"path": "lib.py"}, "observation": "x = 1"},
    ]
    report = {"category_scores": {"security": {"investigation_trace": trace}}}
    agent = {"source": "investigator:security", "category": "security", "file": "app.py"}
    assert [s["tool"] for s in ui.evidence_steps(agent, report)] == ["list_directory", "read_file"]
    assert ui.evidence_steps({**agent, "source": "bandit"}, report) == []  # scanners need no trace
    assert ui.evidence_steps({**agent, "file": None}, report) == []
