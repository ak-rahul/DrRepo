import json

import pytest

from drrepo import reporting as history
from drrepo.exporters import to_json, to_markdown, to_sarif
from drrepo.models import (
    Category,
    CategoryFinding,
    InvestigationPlan,
    Issue,
    Location,
    Severity,
    ToolCallTrace,
)
from drrepo.reporting import grade, quick_wins, synthesize_report, weighted_overall


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


class TestSynthesizer:
    def test_unassessed_excluded_and_weights_renormalized(self):
        findings = {
            "security": _finding(Category.SECURITY, 40),
            "documentation": _finding(Category.DOCUMENTATION, 80),
            "code_quality": _finding(Category.CODE_QUALITY, 0, assessed=False),
        }
        # (40*0.30 + 80*0.15) / 0.45
        assert weighted_overall(findings) == pytest.approx(53.3, abs=0.1)
        assert weighted_overall({}) == 0.0

    def test_issue_order_and_category_order(self, report_dict):
        assert [i["severity"] for i in report_dict["issues"]] == ["high", "medium", "low"]
        assert list(report_dict["category_scores"]) == ["documentation", "code_quality", "security"]
        assert report_dict["issue_counts"] == {"critical": 0, "high": 1, "medium": 1, "low": 1}

    def test_quick_wins_dedupe(self):
        issues = [_issue(Severity.LOW, f"t{i}", rec="same") for i in range(3)] + [
            _issue(Severity.HIGH, "h", rec="hard")
        ]
        assert quick_wins(issues) == ["same"]

    @pytest.mark.parametrize(
        ("score", "letter"), [(95, "A"), (85, "B"), (70, "C"), (65, "D"), (10, "F")]
    )
    def test_grade(self, score, letter):
        assert grade(score) == letter


class TestExporters:
    def test_json_roundtrip(self, report_dict):
        assert json.loads(to_json(report_dict)) == report_dict

    def test_markdown(self, report_dict):
        md = to_markdown(report_dict)
        assert "# DrRepo report: octo/demo" in md
        assert "security \\| summary" in md  # pipes inside LLM text escaped in the table
        assert "| Code Quality | n/a |" in md
        assert "## How it investigated" in md and '`read_file({"path": "a.py"})`' in md
        assert "## Investigation plan" in md

    def test_sarif_structure(self, report_dict):
        sarif = json.loads(to_sarif(report_dict))
        run = sarif["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        assert rule_ids == {"bandit/B1", "readme_analyzer"}
        shell = [r for r in run["results"] if r["message"]["text"].startswith("Shell")]
        assert len(shell) == 2  # one result per location
        regions = [r["locations"][0]["physicalLocation"]["region"]["startLine"] for r in shell]
        assert regions == [3, 1]  # missing line -> 1
        no_location = [r for r in run["results"] if r["message"]["text"].startswith("No usage")]
        assert "locations" not in no_location[0]
        security_rule = next(r for r in run["tool"]["driver"]["rules"] if r["id"] == "bandit/B1")
        assert security_rule["properties"]["security-severity"] == "7.5"


class TestHistory:
    def test_attach_and_record(self, tmp_path, report_dict):
        path = tmp_path / "history.json"
        first = history.attach_and_record_history(dict(report_dict), path)
        assert "score_history" not in first
        second = dict(report_dict, overall_score=report_dict["overall_score"] + 5)
        second = history.attach_and_record_history(second, path)
        assert second["score_history"]["overall_score_delta"] == 5
        assert "code_quality" not in second["score_history"]["category_score_deltas"]  # unassessed
        assert not path.with_suffix(".json.tmp").exists()

    def test_cap_per_repo(self, tmp_path, report_dict, monkeypatch):
        monkeypatch.setattr(history, "_MAX_RUNS_PER_REPO", 3)
        path = tmp_path / "h.json"
        for _ in range(5):
            history.record_run(report_dict, path)
        assert len(history.load_history(path)) == 3

    def test_corrupt_file_is_empty(self, tmp_path):
        path = tmp_path / "h.json"
        path.write_text("{not json", encoding="utf-8")
        assert history.load_history(path) == []
