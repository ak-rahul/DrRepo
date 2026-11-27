from unittest.mock import MagicMock

import pytest

from drrepo.config import Config
from drrepo.service import AnalysisService, save_report
from tests.interfaces.test_cli import REPORT


class TestService:
    def test_one_workflow_shared_collaborators_fresh_budget(self, tmp_path):
        workflow = MagicMock()
        workflow.run.side_effect = lambda repo, ctx, description, ref: dict(REPORT)
        client = MagicMock()
        service = AnalysisService(
            Config(groq_api_key="k"),
            llm_client=client,
            workflow=workflow,
            history_path=tmp_path / "h.json",
        )
        service.analyze("https://github.com/octo/demo", deep=False)
        service.analyze("github.com/octo/demo.git")

        (repo1, ctx1, _, _), (repo2, ctx2, _, _) = (c.args for c in workflow.run.call_args_list)
        assert repo1 == repo2 and repo1.full_name == "octo/demo"
        assert ctx1.config.enable_deep_investigation is False  # per-run override...
        assert service.config.enable_deep_investigation is True  # ...doesn't leak
        assert ctx1.llm.client is ctx2.llm.client is client
        assert ctx1.llm.breaker is ctx2.llm.breaker is service.breaker
        assert ctx1.cache is ctx2.cache is service.cache
        assert ctx1.llm.budget is not ctx2.llm.budget  # fresh per run
        assert service.latest_report("OCTO/demo")["overall_score"] == 42.0
        assert service.latest_report("https://github.com/octo/demo") is not None
        assert [r["repository"] for r in service.list_reports()] == ["octo/demo"]
        assert (tmp_path / "h.json").exists()  # history recorded

    def test_no_api_key_means_no_llm_client(self):
        assert AnalysisService(Config(groq_api_key=""), workflow=MagicMock()).llm_client is None

    def test_save_report(self, tmp_path):
        paths = save_report(REPORT, tmp_path / "out", ("json", "md"))
        assert [p.suffix for p in paths] == [".json", ".md"]
        assert paths[0].name.startswith("octo__demo_")


def test_ref_is_validated_and_forwarded(tmp_path):
    workflow = MagicMock()
    workflow.run.return_value = dict(REPORT)
    service = AnalysisService(Config(), workflow=workflow, history_path=tmp_path / "h.json")
    service.analyze("https://github.com/octo/demo", ref="v1.0", record_history=False)
    assert workflow.run.call_args.args[3] == "v1.0"
    with pytest.raises(ValueError, match="not a valid"):
        service.analyze("https://github.com/octo/demo", ref="--upload-pack=x")


def test_deep_estimate_comes_from_history_within_bounds(tmp_path):
    import json

    path = tmp_path / "h.json"
    workflow = MagicMock()
    workflow.run.return_value = dict(REPORT)
    service = AnalysisService(
        Config(estimated_tokens_per_deep_investigation=10_000), workflow=workflow, history_path=path
    )

    def estimate_after(tokens: list[int]) -> int | None:
        runs = [
            {
                "repo_key": "https://github.com/octo/demo",
                "timestamp": "2026-11-01T00:00:00+00:00",
                "overall_score": 40.0,
                "deep_tokens": tokens,
            }
        ]
        path.write_text(json.dumps(runs), encoding="utf-8")
        service.analyze("https://github.com/octo/demo")
        return workflow.run.call_args.args[1].deep_investigation_tokens

    assert estimate_after([]) is None  # nothing measured: the configured estimate applies
    assert estimate_after([6_000, 8_000]) == 7_000
    assert estimate_after([400]) == 2_500  # at least a quarter of the configured value
    assert estimate_after([900_000]) == 40_000  # at most four times
    service.analyze("https://github.com/octo/demo", record_history=False)
    assert workflow.run.call_args.args[1].deep_investigation_tokens is None


def _scored(security, issues=(), depth="shallow"):
    report = dict(REPORT)
    report["category_scores"] = {
        "security": {"score": security, "assessed": True, "investigation_depth": depth}
    }
    report["issues"] = list(issues)
    report["overall_score"] = security
    return report


def test_compare_runs_both_commits_and_goes_deep_only_where_worse(tmp_path):
    new_issue = dict(REPORT["issues"][0], title="New", rule_id="B999")
    runs = iter([_scored(80), _scored(60, [new_issue]), _scored(55, [new_issue], depth="deep")])
    workflow = MagicMock()
    workflow.run.side_effect = lambda *_a: next(runs)
    service = AnalysisService(
        Config(), llm_client=MagicMock(), workflow=workflow, history_path=tmp_path / "h.json"
    )
    diff = service.compare("https://github.com/octo/demo", "main", "b" * 40, deep=True)

    (_, base_ctx, _, base_ref), (_, head_ctx, _, head_ref), (_, deep_ctx, _, deep_ref) = (
        c.args for c in workflow.run.call_args_list
    )
    assert (base_ref, head_ref, deep_ref) == ("main", "b" * 40, "b" * 40)
    assert not base_ctx.config.enable_deep_investigation
    assert not head_ctx.config.enable_deep_investigation
    assert deep_ctx.config.enable_deep_investigation and deep_ctx.deep_allowed == {"security"}
    assert diff["category_deltas"]["security"]["delta"] == -25.0
    assert [i["title"] for i in diff["new_issues"]] == ["New"]
    assert diff["deep_categories"] == ["security"]
    assert diff["head_report"]["overall_score"] == 55
    assert not (tmp_path / "h.json").exists()  # a diff never writes score history


def test_compare_skips_the_deep_run_when_nothing_got_worse(tmp_path):
    workflow = MagicMock()
    workflow.run.side_effect = lambda *_a: _scored(80)
    service = AnalysisService(
        Config(), llm_client=MagicMock(), workflow=workflow, history_path=tmp_path / "h.json"
    )
    diff = service.compare("https://github.com/octo/demo", "main", deep=True)
    assert workflow.run.call_count == 2 and diff["deep_categories"] == []
    with pytest.raises(ValueError, match="not a valid"):
        service.compare("https://github.com/octo/demo", "--upload-pack=x")


def test_save_diff_leaves_out_the_head_report(tmp_path):
    import json

    from drrepo.report.diff import diff_reports
    from drrepo.service import save_diff

    diff = diff_reports(_scored(80), _scored(70))
    diff["head_report"] = _scored(70)
    json_path, md_path = save_diff(diff, tmp_path)
    assert json_path.name.startswith("octo__demo_diff_") and md_path.suffix == ".md"
    assert "head_report" not in json.loads(json_path.read_text(encoding="utf-8"))
    assert md_path.read_text(encoding="utf-8").startswith("### DrRepo diff: octo/demo: -10.0")
