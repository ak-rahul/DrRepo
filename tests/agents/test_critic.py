"""Critic pass: bounded verdicts on severe agent findings."""

from unittest.mock import MagicMock

import pytest

from drrepo.agents.critic import (
    DISPUTED_MARK,
    MAX_FINDINGS_PER_CATEGORY,
    CriticReviewOutput,
    CriticVerdictOutput,
    build_input,
    candidates,
    review,
    snippet,
)
from drrepo.agents.grounding import UNVERIFIED_MARK
from drrepo.agents.llm import LLMRuntime, TokenBudget
from drrepo.errors import CircuitOpenError
from drrepo.models import Category, Issue, Location, Severity


def _issue(severity=Severity.HIGH, title="Shell injection", source="investigator:security", line=3):
    return Issue(
        severity,
        Category.SECURITY,
        title,
        "user input reaches subprocess",
        "quote it",
        source,
        rule_id="agent-finding",
        locations=[Location("app.py", line)],
    )


@pytest.fixture
def clone(tmp_path):
    lines = [f"line_{n} = {n}" for n in range(1, 61)]
    (tmp_path / "app.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(tmp_path)


def _llm(*verdicts, error=None):
    client = MagicMock()
    invoke = client.with_structured_output.return_value.invoke
    if error is not None:
        invoke.side_effect = error
    else:
        invoke.return_value = CriticReviewOutput(
            verdicts=[
                CriticVerdictOutput(finding=n, verdict=v, reason=f"r{n}") for n, v in verdicts
            ]
        )
    return LLMRuntime(client=client, budget=TokenBudget(100_000), label="critic")


def test_only_grounded_severe_agent_findings_are_candidates():
    issues = [
        _issue(),
        _issue(Severity.CRITICAL),
        _issue(Severity.MEDIUM),  # not severe
        _issue(source="bandit"),  # deterministic: never second-guessed
        _issue(title=f"{UNVERIFIED_MARK} Guess"),  # grounding already lowered its trust
    ]
    assert candidates(issues) == [0, 1]


def test_snippet_marks_the_cited_line_and_stays_in_the_window(clone):
    text = snippet(clone, _issue(line=30))
    assert ">   30  line_30 = 30" in text
    assert "   18  line_18" in text and "line_17 " not in text and "line_43" not in text
    head = snippet(clone, _issue(line=None))
    assert "    1  line_1 = 1" in head and "line_41" not in head
    assert snippet(clone, Issue(Severity.HIGH, Category.SECURITY, "t", "", "", "x")) == (
        "(no file cited)"
    )


def test_input_fences_code_as_data(clone):
    text = build_input([_issue()], [0], clone)
    assert text.startswith("Finding 1 [high] Shell injection")
    assert "Cited: app.py:3" in text and "<<<CODE\n" in text and "\nCODE>>>" in text


def test_verdicts_are_applied_within_bounds(clone):
    issues = [
        _issue(title="A"),
        _issue(Severity.CRITICAL, title="B"),
        _issue(title="C"),
        _issue(title="D"),
        _issue(Severity.LOW, title="E"),  # not reviewed
    ]
    llm = _llm((1, "confirmed"), (2, "downgrade"), (3, "reject"), (3, "confirmed"), (9, "reject"))
    result = review(llm, issues, clone)
    by_title = {i.title.removeprefix(f"{DISPUTED_MARK} "): i for i in result.issues}
    assert by_title["A"].severity == Severity.HIGH and by_title["A"] == issues[0]
    assert by_title["B"].severity == Severity.HIGH  # one level, never more
    assert "(Critic: r2)" in by_title["B"].description
    disputed = result.issues[2]
    assert disputed.title == f"{DISPUTED_MARK} C" and disputed.severity == Severity.LOW
    assert by_title["D"] == issues[3]  # unanswered: left as reported
    assert result.issues[4] == issues[4]
    assert len(result.issues) == len(issues)  # nothing is ever removed
    assert result.note() == (
        "Critic reviewed 4 severe agent finding(s): 1 confirmed, 1 downgraded, 1 disputed, "
        "1 unanswered (left as reported)."
    )
    assert llm.budget.used_by("critic") > 0


def test_no_candidates_means_no_call(clone):
    llm = _llm()
    result = review(llm, [_issue(Severity.MEDIUM)], clone)
    llm.client.with_structured_output.assert_not_called()
    assert result.note() is None


def test_a_failed_call_changes_nothing(clone):
    issues = [_issue()]
    result = review(_llm(error=CircuitOpenError("open")), issues, clone)
    assert result.issues == issues
    assert result.note() == (
        "Critic unavailable (CircuitOpenError); severe agent findings were not re-checked."
    )


def test_review_is_capped(clone):
    issues = [_issue(title=f"T{n}") for n in range(MAX_FINDINGS_PER_CATEGORY + 2)]
    result = review(_llm(), issues, clone)
    assert result.reviewed == MAX_FINDINGS_PER_CATEGORY and result.not_reviewed == 2
    assert "2 more were not reviewed" in (result.note() or "")
