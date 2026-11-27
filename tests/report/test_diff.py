"""Diff of two reports: issue identity across commits, deltas, gate, contract, Markdown."""

import copy

import jsonschema
import pytest

from drrepo.report.diff import (
    diff_reports,
    gate,
    issue_identity,
    validate_diff,
    worsened_categories,
)
from drrepo.report.exporters import diff_to_markdown

SHA_A, SHA_B = "a" * 40, "b" * 40


def _issue(title, severity="medium", category="security", source="bandit", rule="B1", **kw):
    issue = {
        "severity": severity,
        "category": category,
        "title": title,
        "description": "",
        "recommendation": "",
        "source": source,
        "rule_id": rule,
        "file": "app.py",
        "line": 3,
        "locations": [{"file": "app.py", "line": 3}],
        "occurrences": 1,
    }
    issue.update(kw)
    return issue


def _report(sha, issues, security=80.0, docs=70.0, docs_assessed=True):
    return {
        "repository": {
            "name": "demo",
            "full_name": "octo/demo",
            "url": "https://github.com/octo/demo",
            "commit_sha": sha,
            "ref": "main",
        },
        "overall_score": round((security + docs) / 2, 1),
        "category_scores": {
            "security": {"score": security, "assessed": True},
            "documentation": {"score": docs, "assessed": docs_assessed},
        },
        "issues": issues,
        "generated_at": "2026-11-27T00:00:00+00:00",
        "drrepo_version": "9.9.9",
    }


def test_identity_ignores_lines_marks_and_counts():
    moved = _issue("Shell", line=40, locations=[{"file": "app.py", "line": 40}])
    assert issue_identity(_issue("Shell")) == issue_identity(moved)
    agent = _issue("Weak hash", source="investigator:security", rule="agent-finding")
    marked = dict(agent, title="[disputed] [unverified] Weak hash")
    assert issue_identity(agent) == issue_identity(marked)
    counted = _issue("bandit B603 (8 occurrences)", rule=None, source="repo_hygiene")
    assert issue_identity(counted) == issue_identity(
        dict(counted, title="bandit B603 (2 occurrences)")
    )
    assert issue_identity(_issue("Shell")) != issue_identity(_issue("Shell", file="other.py"))
    readme = _issue("No usage", category="documentation", source="readme_analyzer", rule=None)
    renamed = dict(readme, file="README.md")
    assert issue_identity(dict(readme, file="README.rst")) == issue_identity(renamed)


@pytest.fixture
def pair():
    base = _report(
        SHA_A,
        [_issue("Shell", rule="B602"), _issue("Old bug", rule="B101"), _issue("Grows", rule="B3")],
    )
    head = _report(
        SHA_B,
        [
            _issue("Shell", rule="B602", line=9),  # moved: unchanged
            _issue("Grows", rule="B3", severity="high", occurrences=4),  # worse
            _issue("New secret", rule="S1", severity="critical"),
            _issue("No usage", category="documentation", source="readme_analyzer", rule=None),
        ],
        security=60.0,
        docs_assessed=False,
    )
    return base, head


def test_new_fixed_worsened_and_deltas(pair):
    diff = diff_reports(*pair)
    assert [i["title"] for i in diff["new_issues"]] == ["New secret", "No usage"]  # by severity
    assert [i["title"] for i in diff["fixed_issues"]] == ["Old bug"]
    [worse] = diff["worsened_issues"]
    assert (worse["issue"]["title"], worse["base_severity"], worse["base_occurrences"]) == (
        "Grows",
        "medium",
        1,
    )
    assert diff["unchanged_issues"] == 1
    assert diff["category_deltas"]["security"] == {"base": 80.0, "head": 60.0, "delta": -20.0}
    assert diff["category_deltas"]["documentation"]["delta"] is None  # head unassessed
    assert diff["overall_delta"] == pytest.approx(-10.0)  # 75 -> 65
    assert (diff["base"]["commit_sha"], diff["head"]["commit_sha"]) == (SHA_A, SHA_B)
    assert worsened_categories(diff) == ["documentation", "security"]
    validate_diff(diff)


def test_identical_reports_diff_to_nothing(pair):
    base, _ = pair
    diff = diff_reports(base, copy.deepcopy(base))
    assert not (diff["new_issues"] or diff["fixed_issues"] or diff["worsened_issues"])
    assert diff["overall_delta"] == 0 and worsened_categories(diff) == []
    assert gate(diff, "low", 0) == []


def test_gate(pair):
    diff = diff_reports(*pair)
    assert gate(diff) == []
    assert gate(diff, fail_on_new="critical") == [
        "1 new or worsened issue(s) at critical severity or above"
    ]
    assert gate(diff, fail_on_new="high")[0].startswith("2 new or worsened")  # + "Grows" (high)
    assert gate(diff, max_score_drop=5) == ["overall score fell -10.0 (allowed: -5)"]
    assert gate(diff, max_score_drop=15) == []


def test_contract_rejects_unknown_fields(pair):
    diff = diff_reports(*pair)
    with pytest.raises(jsonschema.ValidationError):
        validate_diff(dict(diff, surprise=1))
    broken = copy.deepcopy(diff)
    broken["new_issues"][0]["severity"] = "urgent"
    with pytest.raises(jsonschema.ValidationError):
        validate_diff(broken)


def test_markdown_is_short_and_inert(pair):
    base, head = pair
    head["issues"][2]["title"] = "New secret for @octocat <img src=x>"
    text = diff_to_markdown(diff_reports(base, head))
    assert text.startswith("### DrRepo diff: octo/demo: -10.0")
    assert "`aaaaaaaaaaaa` (75) → `bbbbbbbbbbbb` (65)" in text
    assert "2 new, 1 worse, 1 fixed, 1 unchanged" in text
    assert "| Security | 80 | 60 | -20.0 |" in text
    assert "(was medium, ×1)" in text
    assert "@​octocat" in text and "<img" not in text
