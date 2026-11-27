"""The composite GitHub Action (action.yml) and the example workflow agree with each other and the CLI."""

import re
from pathlib import Path

import yaml

from drrepo.report.exporters import FORMATS

ROOT = Path(__file__).resolve().parent.parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
EXAMPLE = yaml.safe_load((ROOT / "examples" / "github-workflow.yml").read_text(encoding="utf-8"))
STEPS = ACTION["runs"]["steps"]


def _text(node: object) -> str:
    return yaml.safe_dump(node, sort_keys=False)


def test_every_referenced_input_and_step_exists():
    used_inputs = set(re.findall(r"inputs\.([a-z0-9-]+)", _text(ACTION["runs"])))
    assert used_inputs == set(ACTION["inputs"])  # none missing, none unused
    step_ids = {s["id"] for s in STEPS if "id" in s}
    referenced = set(re.findall(r"steps\.([a-z0-9-]+)\.outputs", _text(ACTION)))
    assert referenced <= step_ids
    for output in ACTION["outputs"].values():
        assert output["value"].startswith("${{ steps.")


def test_inputs_never_expand_inside_scripts():
    # Template injection: run scripts read inputs through env, never `${{ }}` inline.
    for step in STEPS:
        if "run" in step:
            assert "${{" not in step["run"], step.get("name")


def test_default_formats_are_cli_formats():
    defaults = ACTION["inputs"]["formats"]["default"].split(",")
    assert set(defaults) <= set(FORMATS)
    assert "summary" in FORMATS  # the step summary and PR comment depend on it


def test_third_party_actions_are_pinned_to_commits():
    for step in STEPS:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_example_workflow_uses_only_real_inputs():
    [step] = [s for s in EXAMPLE["jobs"]["audit"]["steps"] if s.get("id") == "drrepo"]
    assert step["uses"].split("@")[0] == "ak-rahul/DrRepo"
    assert set(step["with"]) <= set(ACTION["inputs"])
    formats = step["with"]["formats"].split(",")
    assert set(formats) <= set(FORMATS)
