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
