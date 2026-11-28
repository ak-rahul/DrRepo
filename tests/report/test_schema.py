"""Every report shape the code can produce satisfies the published schema."""

import copy

import jsonschema
import pytest

from drrepo.agents.llm import LLMRuntime, TokenBudget
from drrepo.config import Config
from drrepo.models import REPORT_SCHEMA_VERSION, RepoRef
from drrepo.pipeline import RunContext, Workflow
from drrepo.report.schema import load_schema, validate
from drrepo.report.store import JsonFileStore, attach_history
from drrepo.report.suppressions import Suppression


def _run(**ctx_kwargs):
    ctx_kwargs.setdefault("llm", LLMRuntime(client=None))
    ctx = RunContext(config=Config(), **ctx_kwargs)
    return Workflow().run(RepoRef("octo", "demo"), ctx)


def test_schema_is_itself_valid_and_versioned():
    schema = load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert REPORT_SCHEMA_VERSION.count(".") == 1


def test_synthesized_report_is_valid(report_dict):
    validate(report_dict)
    assert report_dict["schema_version"] == REPORT_SCHEMA_VERSION


def test_full_pipeline_reports_are_valid(pipeline, tmp_path):
    validate(_run())
    with_extras = _run(
        llm=LLMRuntime(client=None, budget=TokenBudget(1000)),
        suppressions=[Suppression("bandit/B605", "by design", expires=None)],
    )
    assert with_extras["suppressed"] and "llm_usage" in with_extras
    validate(with_extras)
    path = tmp_path / "history.json"
    attach_history(copy.deepcopy(with_extras), JsonFileStore(path))
    second = attach_history(copy.deepcopy(with_extras), JsonFileStore(path))
    assert "score_history" in second
    validate(second)


@pytest.mark.parametrize(
    "mutate",
    [
        # Undocumented fields fail: the schema is the contract.
        lambda r: r.update(unexpected_field=1),
        lambda r: r.update(overall_score=101),
        lambda r: r["issues"].append({"severity": "urgent"}),
        lambda r: r["repository"].update(commit_sha="not-a-sha"),
        lambda r: r.pop("schema_version"),
    ],
)
def test_contract_violations_are_caught(report_dict, mutate):
    broken = copy.deepcopy(report_dict)
    mutate(broken)
    with pytest.raises(jsonschema.ValidationError):
        validate(broken)
