import copy
import json

import pytest
from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator

from drrepo.report.exporters import (
    purl,
    to_cyclonedx,
    to_json,
    to_markdown,
    to_sarif,
    to_summary,
)
from drrepo.report.schema import validate
from drrepo.report.synthesis import dependency_inventory


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


AUDIT = {
    "packages": [
        {"ecosystem": "PyPI", "name": "Jinja2", "version": "3.1.2", "scope": "runtime"},
        {"ecosystem": "npm", "name": "@babel/core", "version": "7.0.0", "scope": "dev"},
        {"ecosystem": "Go", "name": "golang.org/x/net", "version": "v0.1.0", "scope": "runtime"},
        {"ecosystem": "Hex", "name": "plug", "version": "1.0.0", "scope": "runtime"},
    ],
    "licenses": [
        {"ecosystem": "PyPI", "package": "Jinja2", "version": "3.1.2", "license": "BSD-3-Clause"},
        {
            "ecosystem": "Go",
            "package": "golang.org/x/net",
            "version": "v0.1.0",
            "license": "Custom License",
        },
    ],
    "vulnerabilities": [
        {"ecosystem": "PyPI", "package": "Jinja2", "version": "3.1.2", "vuln_id": "GHSA-h5c8"},
        {"ecosystem": "PyPI", "package": "Jinja2", "version": "3.1.2", "vuln_id": "GHSA-q2x7"},
    ],
}


@pytest.fixture
def sbom_report(report_dict):
    report = copy.deepcopy(report_dict)
    report["dependencies"] = dependency_inventory(AUDIT)
    report["repository"]["commit_sha"] = "c" * 40
    report["issues"].append(
        {
            "severity": "high",
            "category": "dependencies",
            "title": "Jinja2@3.1.2: 2 known vulnerabilities",
            "description": "",
            "recommendation": "Upgrade Jinja2 to 3.1.6 or later.",
            "source": "osv.dev",
            "rule_id": "GHSA-h5c8",
            "file": None,
            "line": None,
            "locations": [],
            "occurrences": 1,
        }
    )
    return report


@pytest.mark.parametrize(
    ("ecosystem", "name", "version", "expected"),
    [
        ("PyPI", "Jinja2", "3.1.2", "pkg:pypi/jinja2@3.1.2"),
        ("PyPI", "typing_extensions", "4.0", "pkg:pypi/typing-extensions@4.0"),
        ("npm", "@babel/core", "7.0.0", "pkg:npm/%40babel/core@7.0.0"),
        ("Go", "golang.org/x/net", "v0.1.0", "pkg:golang/golang.org/x/net@v0.1.0"),
        ("Maven", "org.apache:commons", "1.0", "pkg:maven/org.apache/commons@1.0"),
        ("npm", "left-pad", "1.0.0+build/1", "pkg:npm/left-pad@1.0.0%2Bbuild%2F1"),
        ("Hex", "plug", "1.0.0", None),
    ],
)
def test_purl(ecosystem, name, version, expected):
    assert purl(ecosystem, name, version) == expected


def test_dependency_inventory_merges_licenses_and_advisories():
    inventory = {d["name"]: d for d in dependency_inventory(AUDIT)}
    assert inventory["Jinja2"]["license"] == "BSD-3-Clause"
    assert inventory["Jinja2"]["vulnerabilities"] == ["GHSA-h5c8", "GHSA-q2x7"]
    assert inventory["@babel/core"] == {
        **AUDIT["packages"][1],
        "license": None,
        "vulnerabilities": [],
    }
    assert dependency_inventory(None) == []


def test_report_with_dependencies_matches_the_schema(sbom_report):
    validate(sbom_report)


def test_cyclonedx_is_valid_and_complete(sbom_report):
    text = to_cyclonedx(sbom_report)
    errors = JsonStrictValidator(SchemaVersion.V1_6).validate_str(text)
    assert errors is None, errors
    bom = json.loads(text)
    components = {c["name"]: c for c in bom["components"]}
    assert components["Jinja2"]["purl"] == "pkg:pypi/jinja2@3.1.2"
    assert components["Jinja2"]["licenses"] == [{"expression": "BSD-3-Clause"}]
    assert components["golang.org/x/net"]["licenses"] == [{"license": {"name": "Custom License"}}]
    assert components["@babel/core"]["scope"] == "optional"  # dev tooling
    assert "purl" not in components["plug"] and components["plug"]["bom-ref"] == "Hex:plug@1.0.0"
    vulns = {v["id"]: v for v in bom["vulnerabilities"]}
    assert vulns["GHSA-h5c8"]["affects"] == [{"ref": "pkg:pypi/jinja2@3.1.2"}]
    assert vulns["GHSA-h5c8"]["ratings"][0]["severity"] == "high"
    assert "ratings" not in vulns["GHSA-q2x7"]  # only the issue's lead advisory is rated
    assert bom["metadata"]["component"]["version"] == "c" * 40
    # Same repository at the same commit, same serial number.
    assert json.loads(to_cyclonedx(sbom_report))["serialNumber"] == bom["serialNumber"]


def test_cyclonedx_without_dependencies_is_still_valid(report_dict):
    text = to_cyclonedx(report_dict)
    assert JsonStrictValidator(SchemaVersion.V1_6).validate_str(text) is None
    assert json.loads(text)["components"] == []


def test_summary_is_short_and_inert(report_dict):
    report = copy.deepcopy(report_dict)
    report["issues"][0]["title"] = (
        "req@1.0: ping @octocat ![x](https://evil.example/t.png) <img src=x>"
    )
    report["issues"] += [dict(report["issues"][-1], title=f"filler {n}") for n in range(12)]
    text = to_summary(report, max_issues=5)
    assert text.startswith("### DrRepo: octo/demo: ")
    assert "| Security | 40 |" in text and "| Code Quality | n/a |" in text
    assert "@\u200boctocat" in text and "@octocat" not in text  # no notification
    assert "req@1.0" in text  # package versions are not mentions
    assert "![" not in text and "<img" not in text  # no remote content
    assert "`a.py:3`" in text
    assert "…and 10 more in the full report." in text
    assert len(text) < 3000


def test_summary_without_issues(report_dict):
    report = dict(report_dict, issues=[], suppressed=[])
    assert "No issues found." in to_summary(report)
