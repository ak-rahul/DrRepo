"""Deterministic documentation checks: links and anchors, docstrings, documented commands."""

import json

import pytest

from drrepo.agents.analysts.documentation import (
    DOC_CHECK_MAX_PENALTY,
    DocumentationAnalyst,
    doc_check_issues,
)
from drrepo.recon.doc_checks import anchors, collect_doc_checks, github_slug
from tests.conftest import ok

README = """\
# Demo

See [usage](docs/usage.md#running-it), [missing](docs/nope.md),
[bad anchor](docs/usage.md#no-such-heading), [self](#install), [site](https://example.com/x),
[escape](../outside.md), and [dir](docs/).

## Install

```bash
$ uv run demo --help
npm run build
npm run lint
make test
make deploy
yarn install
demo-tool start
```

Inline `[not a link](missing.md)` is code.

[ref]: docs/gone.md
"""

USAGE = """\
# Usage

## Running it

## Running it

<a id="custom-anchor"></a>
Back to [the top](../README.md#demo) and [repeat](#running-it-1), [custom](#custom-anchor).

```markdown
[inside a fence](nowhere.md)
```
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "usage.md").write_text(USAGE, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[project.scripts]\ndemo = "demo:main"\n', encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "@acme/demo-tool", "scripts": {"build": "tsc"}}), encoding="utf-8"
    )
    (tmp_path / "Makefile").write_text("test:\n\tpytest\nVAR := 1\n", encoding="utf-8")
    pkg = tmp_path / "demo"
    pkg.mkdir()
    (pkg / "api.py").write_text(
        'def documented():\n    """Yes."""\n\n\ndef bare():\n    pass\n\n\n'
        'def _private():\n    pass\n\n\nclass Client:\n    """Doc."""\n\n'
        "    def get(self):\n        pass\n\n    def _helper(self):\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    return tmp_path


def test_github_slugs_and_anchors():
    assert github_slug("Running it") == "running-it"
    assert github_slug("In CI: the `GitHub` Action!") == "in-ci-the-github-action"
    assert github_slug("[Link](x.md) and *emphasis*") == "link-and-emphasis"
    found = anchors(USAGE)
    assert {"usage", "running-it", "running-it-1", "custom-anchor"} <= found


def test_links(repo):
    data = collect_doc_checks(str(repo)).data
    broken = {(b["file"], b["target"]): b["reason"] for b in data["broken_links"]}
    assert broken == {
        ("README.md", "docs/nope.md"): "file not found",
        ("README.md", "docs/usage.md#no-such-heading"): "anchor not found",
        ("README.md", "../outside.md"): "points outside the repository",
        ("README.md", "docs/gone.md"): "file not found",  # reference-style definition
    }
    assert data["markdown_files"] == ["README.md", "docs/usage.md"]
    assert data["links_checked"] == 10  # 7 + 3; externals are skipped, never fetched


def test_commands(repo):
    data = collect_doc_checks(str(repo)).data
    missing = {m["command"]: m["reason"] for m in data["missing_commands"]}
    assert missing == {
        "npm run lint": "package.json has no 'lint' script",
        "make deploy": "the Makefile has no 'deploy' target",
        "demo-tool start": "'demo-tool' is not a declared entry point",
    }
    assert data["commands_checked"] == 6  # uv run demo, build, lint, test, deploy, demo-tool


def test_docstrings_cover_public_package_code_only(repo):
    docs = collect_doc_checks(str(repo)).data["docstrings"]
    assert (docs["public"], docs["documented"]) == (4, 2)  # documented, bare, Client, Client.get
    assert {u["name"] for u in docs["undocumented"]} == {"bare", "get"}


def test_issues_and_bounded_score(repo):
    checks = collect_doc_checks(str(repo)).data
    checks["docstrings"] = {"public": 40, "documented": 4, "coverage": 0.1, "undocumented": []}
    issues = {i.rule_id: i for i in doc_check_issues(checks, "README.md")}
    assert (
        issues["broken-link"].occurrences == 4 and issues["broken-link"].severity.value == "medium"
    )
    assert issues["docstring-coverage"].severity.value == "medium"  # under 20%
    assert issues["missing-command"].locations[0].file == "README.md"

    readme = {
        "quality_score": 80.0,
        "word_count": 400,
        "missing_sections": [],
        "code_block_count": 2,
    }
    recon = {
        "readme": ok(readme, name="readme"),
        "repo_layout": ok({"readme_path": "README.md", "file_structure": {}}, name="repo_layout"),
    }
    clean = DocumentationAnalyst().assess(recon)
    recon["doc_checks"] = ok(checks, name="doc_checks")
    checked = DocumentationAnalyst().assess(recon)
    assert clean.score == 80.0
    assert checked.score == 80.0 - DOC_CHECK_MAX_PENALTY  # bounded, however many findings
    assert "minus 15 for documentation checks" in checked.summary


def test_no_clone_is_skipped(tmp_path):
    assert collect_doc_checks(str(tmp_path / "missing")).status.value == "skipped"


def test_directive_fences_and_prose_are_not_commands(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "click"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "```{versionchanged} 9.0\nClick 9.0. Use a temporary directory.\n```\n\n"
        "```\nclick --help\n```\n",
        encoding="utf-8",
    )
    missing = collect_doc_checks(str(tmp_path)).data["missing_commands"]
    assert [m["command"] for m in missing] == ["click --help"]  # no entry point declared


def test_sphinx_myst_cross_references_are_not_file_links(tmp_path):
    # attrs-style MyST docs: [](attrs.frozen) and [](api-validators) name objects and
    # labels; "(label)=" defines an anchor. Only real file targets are checked there.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "conf.py").write_text("project = 'x'\n", encoding="utf-8")
    (tmp_path / "docs" / "api.md").write_text("(api-validators)=\n# API\n", encoding="utf-8")
    (tmp_path / "docs" / "index.md").write_text(
        "See [](attrs.frozen), [validators](api-validators), [](genindex),\n"
        "[the API](api.md#api-validators) and [gone](missing.md).\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("[contributing](CONTRIBUTING)\n", encoding="utf-8")
    data = collect_doc_checks(str(tmp_path)).data
    assert sorted((b["file"], b["target"]) for b in data["broken_links"]) == [
        ("README.md", "CONTRIBUTING"),  # outside the Sphinx tree: still a file link
        ("docs/index.md", "missing.md"),
    ]
