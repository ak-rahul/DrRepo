"""`drrepo eval` logic: manifest parsing, summaries, regression detection, precision."""

import json
from pathlib import Path

import pytest

from drrepo.config import Config
from drrepo.evaluation import (
    EvalCase,
    compare,
    finding_key,
    load_cases,
    load_labels,
    read_baseline,
    render_markdown,
    run_cases,
    summarize,
    write_baseline,
)
from drrepo.interfaces import cli

SHA = "a" * 40
CASE = EvalCase("demo", "https://github.com/octo/demo", SHA)


def _report(security=80.0, extra_issues=(), assessed=True):
    issues = [
        {
            "title": "Shell",
            "category": "security",
            "source": "bandit",
            "rule_id": "B602",
            "file": "a.py",
        },
        *extra_issues,
    ]
    return {
        "repository": {"commit_sha": SHA},
        "overall_score": 75.0,
        "category_scores": {
            "security": {
                "score": security,
                "assessed": assessed,
                "investigation_depth": "deep",
                "investigation_trace": [{"tool": "read_file"}],
            },
            "documentation": {"score": 60.0, "assessed": True, "investigation_depth": "shallow"},
        },
        "issues": issues,
        "llm_usage": {"used_tokens": 1234},
    }


AGENT = {
    "title": "[unverified] Weak hash",
    "category": "security",
    "source": "investigator:security",
    "rule_id": "agent-finding",
    "file": "b.py",
}


def test_manifest_requires_full_shas_and_unique_names(tmp_path):
    path = tmp_path / "repos.toml"
    path.write_text(
        '[[case]]\nname = "x"\nurl = "https://github.com/a/b"\nref = "abc"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="40-character"):
        load_cases(path)
    dup = f'[[case]]\nname = "x"\nurl = "u"\nref = "{SHA}"\n' * 2
    path.write_text(dup, encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_cases(path)


def test_shipped_manifest_is_valid():
    cases = load_cases(Path("evals/repos.toml"))
    assert len(cases) >= 3 and all(len(c.ref) == 40 for c in cases)


def test_labels_validate_verdicts(tmp_path):
    path = tmp_path / "labels.toml"
    path.write_text('[labels]\n"k" = "maybe"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="true_positive"):
        load_labels(path)
    assert load_labels(tmp_path / "missing.toml") == {}


def test_finding_key_ignores_the_unverified_mark():
    plain = dict(AGENT, title="Weak hash", rule_id=None)
    marked = dict(AGENT, rule_id=None)
    assert finding_key("demo", plain) == finding_key("demo", marked)


def test_summarize_extracts_comparable_essentials():
    summary = summarize(CASE, _report(extra_issues=[AGENT]), 12.34)
    assert summary["categories"] == {"security": 80.0, "documentation": 60.0}
    assert summary["agent_findings"] == ["demo|security|investigator:security|agent-finding|b.py"]
    assert summary["unverified_agent_findings"] == 1
    assert summary["deep_categories"] == ["security"]
    assert (summary["tool_calls"], summary["tokens"], summary["elapsed_seconds"]) == (1, 1234, 12.3)


def test_compare_flags_drops_beyond_tolerance_and_finding_changes():
    baseline = {"demo": summarize(CASE, _report(security=80.0), 1)}
    within = compare({"demo": summarize(CASE, _report(security=76.0), 1)}, baseline, tolerance=5)
    assert not within.regressed
    worse = compare(
        {"demo": summarize(CASE, _report(security=60.0, extra_issues=[AGENT]), 1)}, baseline
    )
    [diff] = worse.cases
    assert worse.regressed and diff.regressions == ["security fell -20.0"]
    assert diff.new_findings == ["demo|security|investigator:security|agent-finding|b.py"]
    unassessed = compare({"demo": summarize(CASE, _report(assessed=False), 1)}, baseline)
    assert "security is no longer assessed" in unassessed.cases[0].regressions


def test_missing_baseline_and_failed_cases_are_regressions():
    current = {"demo": summarize(CASE, _report(), 1), "bad": {"case": "bad", "error": "boom"}}
    comparison = compare(current, {})
    assert comparison.regressed
    assert "no baseline" in comparison.cases[0].regressions[0]
    assert comparison.cases[1].error == "boom"


def test_precision_counts_only_labeled_agent_findings():
    key = "demo|security|investigator:security|agent-finding|b.py"
    current = {"demo": summarize(CASE, _report(extra_issues=[AGENT]), 1)}
    baseline = {"demo": summarize(CASE, _report(), 1)}
    assert compare(current, baseline).agent_precision is None
    labeled = compare(current, baseline, labels={key: "false_positive"})
    assert (labeled.agent_precision, labeled.labeled_agent_findings) == (0.0, 1)


def test_markdown_table_and_baseline_round_trip(tmp_path):
    current = {"demo": summarize(CASE, _report(security=60.0), 1)}
    baseline = {"demo": summarize(CASE, _report(security=80.0), 1)}
    md = render_markdown(compare(current, baseline), current, 5)
    assert "REGRESSED" in md and "60 (-20.0)" in md and "regression: security fell" in md

    path = tmp_path / "baseline.json"
    write_baseline(path, current)
    assert read_baseline(path) == json.loads(json.dumps(current))
    with pytest.raises(ValueError, match="failed cases"):
        write_baseline(path, {"x": {"error": "boom"}})


def test_run_cases_records_failures_without_aborting():
    def analyze(case):
        if case.name == "bad":
            raise RuntimeError("clone failed")
        return _report()

    results = run_cases(analyze, [EvalCase("bad", "u", SHA), CASE])
    assert results["bad"]["error"] == "RuntimeError: clone failed"
    assert results["demo"]["overall"] == 75.0


def test_cli_eval_compares_and_returns_regression_code(monkeypatch, tmp_path, capsys):
    manifest = tmp_path / "repos.toml"
    manifest.write_text(
        f'[[case]]\nname = "demo"\nurl = "https://github.com/octo/demo"\nref = "{SHA}"\n',
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    write_baseline(baseline, {"demo": summarize(CASE, _report(security=90.0), 1)})

    class Service:
        def __init__(self, config):
            assert config.enable_score_history is False

        def analyze(self, url, **kwargs):
            assert kwargs["ref"] == SHA and kwargs["deep"] is False
            return _report(security=50.0)

    monkeypatch.setattr("drrepo.service.AnalysisService", Service)
    monkeypatch.setattr(cli, "_load_config", lambda _e: Config())
    argv = [
        "eval",
        "--manifest",
        str(manifest),
        "--baseline",
        str(baseline),
        "--labels",
        str(tmp_path / "l.toml"),
        "--log-file",
        "",
    ]
    assert cli.main(argv) == cli.EXIT_FAIL_UNDER
    assert "security fell -40.0" in capsys.readouterr().out


def test_collector_failures_are_environment_problems_not_drift(tmp_path):
    baseline = {"demo": summarize(CASE, _report(), 1)}
    degraded_report = _report(security=10.0)
    degraded_report["collector_status"] = {
        "github_metadata": {"status": "error", "detail": "rate limited"}
    }
    current = {"demo": summarize(CASE, degraded_report, 1)}
    [diff] = compare(current, baseline).cases
    assert diff.regressions == [
        "environment: github_metadata failed (rate limited); scores not comparable"
    ]
    assert diff.category_deltas == {}  # no misleading score deltas
    with pytest.raises(ValueError, match="degraded run"):
        write_baseline(tmp_path / "b.json", current)
