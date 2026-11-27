import json

from drrepo.report.exporters import to_json, to_markdown, to_sarif


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


def test_commit_appears_in_markdown_and_sarif_provenance(report_dict):
    report = dict(report_dict)
    report["repository"] = {**report["repository"], "commit_sha": "c" * 40, "ref": "v1.0"}
    assert f"**Commit:** `{'c' * 12}` (v1.0)" in to_markdown(report)
    [run] = json.loads(to_sarif(report))["runs"]
    assert run["versionControlProvenance"] == [
        {"repositoryUri": "https://github.com/octo/demo", "revisionId": "c" * 40, "branch": "v1.0"}
    ]


def test_no_provenance_without_a_commit(report_dict):
    [run] = json.loads(to_sarif(report_dict))["runs"]
    assert "versionControlProvenance" not in run
