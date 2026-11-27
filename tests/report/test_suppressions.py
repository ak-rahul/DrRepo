"""Suppressions: parsing, matching, expiry, trust model, scoring, and exports."""

import json
import tomllib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from drrepo.agents.llm import LLMRuntime
from drrepo.config import Config
from drrepo.models import Category, Issue, Location, RepoRef, Severity
from drrepo.pipeline import RunContext, Workflow
from drrepo.report.exporters import to_markdown, to_sarif
from drrepo.report.suppressions import (
    Suppression,
    SuppressionError,
    apply,
    baseline_toml,
    parse,
)
from tests.conftest import ok

TODAY = date(2026, 6, 1)


def _issue(source="bandit", rule="B605", file="src/pager.py", severity=Severity.HIGH):
    return Issue(
        severity,
        Category.SECURITY,
        f"{source} {rule}",
        "d",
        "r",
        source,
        rule_id=rule,
        locations=[Location(file, 3)] if file else [],
    )


def _parse(text):
    return parse(text, origin="local", source_name="test.toml")


def test_parse_valid_entries():
    [s] = _parse(
        '[[suppress]]\nrule = "bandit/B605"\npath = "src/*.py"\nreason = "by design"\nexpires = 2027-01-31\n'
    )
    assert (s.rule, s.path, s.reason, s.expires, s.origin) == (
        "bandit/B605",
        "src/*.py",
        "by design",
        date(2027, 1, 31),
        "local",
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[suppress]]\nrule = "bandit/B605"\n', "needs a non-empty 'reason'"),
        ('[[suppress]]\nreason = "x"\n', "needs a 'rule'"),
        ('[[suppress]]\nrule = "a"\nreason = "x"\nexpires = "soon"\n', "YYYY-MM-DD"),
        ('[[suppress]]\nrule = "a"\nreason = "x"\ntypo = 1\n', "unknown keys"),
        ("not = [toml", "not valid TOML"),
    ],
)
def test_parse_rejects_malformed_entries_with_a_precise_message(text, message):
    with pytest.raises(SuppressionError, match=message):
        _parse(text)


def test_matching_by_rule_wildcard_and_path():
    issue = _issue()
    assert Suppression("bandit/B605", "r").matches(issue)
    assert Suppression("bandit/*", "r").matches(issue)
    assert not Suppression("bandit/B602", "r").matches(issue)
    assert Suppression("bandit/B605", "r", path="src/*.py").matches(issue)
    assert not Suppression("bandit/B605", "r", path="tests/*").matches(issue)
    assert not Suppression("bandit/B605", "r", path="src/*").matches(_issue(file=None))
    rule_less = Issue(Severity.LOW, Category.DOCUMENTATION, "t", "d", "r", "readme_analyzer")
    assert Suppression("readme_analyzer", "r").matches(rule_less)


def test_expired_suppressions_stop_applying_and_are_reported():
    active = Suppression("bandit/B605", "r", expires=date(2026, 12, 31))
    expired = Suppression("bandit/B605", "old", expires=date(2026, 1, 1))
    result = apply([_issue()], [expired], TODAY)
    assert result.kept == [_issue()] and result.expired == [expired]
    assert "expired on 2026-01-01" in result.notes()[0]
    assert apply([_issue()], [expired, active], TODAY).suppressed[0][1] is active


def test_baseline_round_trips_into_suppressions():
    issues = [
        _issue().to_dict(),
        _issue().to_dict(),  # duplicate rule+file: one entry
        Issue(
            Severity.LOW, Category.DOCUMENTATION, 'Say "hi"', "d", "r", "readme_analyzer"
        ).to_dict(),
    ]
    text = baseline_toml(issues, reason="baseline 2026-06-01", expires=date(2026, 9, 1))
    assert len(tomllib.loads(text)["suppress"]) == 2
    parsed = _parse(text)
    assert {s.rule for s in parsed} == {"bandit/B605", "readme_analyzer"}
    assert all(s.expires == date(2026, 9, 1) for s in parsed)


# ---- pipeline: scoring, trust model ---------------------------------------


@pytest.fixture
def pipeline(tmp_path, github_data):
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


def _run(config, suppressions=()):
    ctx = RunContext(config=config, llm=LLMRuntime(client=None), suppressions=list(suppressions))
    return Workflow().run(RepoRef("octo", "demo"), ctx)


def test_suppressed_issues_leave_the_score_but_stay_in_the_report(pipeline):
    plain = _run(Config())
    suppressed = _run(Config(), [Suppression("bandit/B605", "launches $PAGER by design")])
    before, after = plain["category_scores"]["security"], suppressed["category_scores"]["security"]
    assert before["score"] < 100 and after["score"] == 100.0
    assert after["issues"] == []
    [entry] = suppressed["suppressed"]
    assert entry["issue"]["rule_id"] == "B605"
    assert entry["suppression"]["reason"] == "launches $PAGER by design"
    assert any("suppressed" in n for n in after["notes"])
    assert suppressed["issue_counts"]["high"] == 0


def test_repository_suppressions_need_explicit_trust(pipeline):
    (pipeline / ".drrepo.toml").write_text(
        '[[suppress]]\nrule = "bandit/*"\nreason = "trust me"\n', encoding="utf-8"
    )
    untrusted = _run(Config())
    assert untrusted["suppressed"] == []
    assert (
        "ignored (TRUST_REPO_SUPPRESSIONS is off)"
        in untrusted["collector_status"]["suppressions"]["detail"]
    )
    trusted = _run(Config(trust_repo_suppressions=True))
    assert trusted["suppressed"][0]["suppression"]["origin"] == "repository"


def test_malformed_repository_file_is_reported_not_fatal(pipeline):
    (pipeline / ".drrepo.toml").write_text("[[suppress]]\nrule = 'x'\n", encoding="utf-8")
    report = _run(Config(trust_repo_suppressions=True))
    status = report["collector_status"]["suppressions"]
    assert status["status"] == "error" and "reason" in status["detail"]
    assert report["category_scores"]["security"]["issues"]  # analysis carried on


# ---- exports ----------------------------------------------------------------


def test_exports_mark_suppressed_issues(report_dict):
    entry = {
        "issue": _issue().to_dict(),
        "suppression": Suppression("bandit/B605", "by design", origin="local").to_dict(),
    }
    report = dict(report_dict, suppressed=[entry])
    sarif = json.loads(to_sarif(report))["runs"][0]
    marked = [r for r in sarif["results"] if r.get("suppressions")]
    assert marked[0]["suppressions"][0] == {
        "kind": "external",
        "status": "accepted",
        "justification": "by design (local)",
    }
    assert "## Suppressed (1)" in to_markdown(report)
