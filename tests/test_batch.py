"""Organization batch mode: listing, a failure-tolerant pool, leaderboard, aggregate SARIF."""

import json

import httpx
import pytest

from drrepo.batch import (
    BatchResult,
    RepositoryListError,
    aggregate_sarif,
    leaderboard,
    leaderboard_markdown,
    list_repositories,
    run_batch,
)
from drrepo.config import Config
from tests.conftest import mock_http
from tests.report.conftest import report_dict  # noqa: F401 - fixture


def _repo(name, **flags):
    return {"html_url": f"https://github.com/octo/{name}", **flags}


def test_lists_an_organizations_public_repositories():
    client = mock_http(
        {
            "GET /orgs/octo/repos": [
                _repo("app"),
                _repo("fork", fork=True),
                _repo("old", archived=True),
                _repo("lib"),
            ]
        }
    )
    assert list_repositories("octo", Config(), http_client=client) == [
        "https://github.com/octo/app",
        "https://github.com/octo/lib",
    ]
    assert len(list_repositories("octo", Config(), include_forks=True, http_client=client)) == 3
    assert list_repositories("octo", Config(), limit=1, http_client=client) == [
        "https://github.com/octo/app"
    ]


def test_falls_back_to_a_user_and_reports_errors():
    user = mock_http(
        {"GET /orgs/someone/repos": httpx.Response(404), "GET /users/someone/repos": [_repo("x")]}
    )
    assert list_repositories("someone", Config(), http_client=user) == ["https://github.com/octo/x"]
    nobody = mock_http({"GET /orgs/": httpx.Response(404), "GET /users/": httpx.Response(404)})
    with pytest.raises(RepositoryListError, match="no GitHub organization or user"):
        list_repositories("nobody", Config(), http_client=nobody)
    limited = mock_http({"GET /orgs/": httpx.Response(403)})
    with pytest.raises(RepositoryListError, match="GH_TOKEN"):
        list_repositories("octo", Config(), http_client=limited)


def test_batch_survives_a_failure_and_ranks_by_score(report_dict):  # noqa: F811
    class Service:
        def analyze(self, url, deep=False):
            if url.endswith("broken"):
                raise ValueError("clone failed")
            score = 80.0 if url.endswith("good") else 40.0
            return {
                **report_dict,
                "overall_score": score,
                "repository": {
                    **report_dict["repository"],
                    "name": url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1],
                },
            }

    urls = [f"https://github.com/octo/{n}" for n in ("weak", "broken", "good")]
    results = run_batch(Service(), urls, workers=2)  # type: ignore[arg-type]
    assert [r.url for r in results] == urls  # input order kept
    rows = leaderboard(results)
    assert [r["repository"] for r in rows] == [
        "octo/good",
        "octo/weak",
        "https://github.com/octo/broken",
    ]
    assert rows[0]["grade"] == "B" and rows[-1]["error"] == "ValueError: clone failed"
    markdown = leaderboard_markdown("octo", rows)
    assert "2 of 3 repositories analyzed." in markdown
    assert "| 1 | [octo/good](https://github.com/octo/good) | 80.0 (B)" in markdown
    assert "failed: ValueError: clone failed" in markdown
    sarif = json.loads(aggregate_sarif([r.report for r in results if r.report]))
    assert sarif["version"] == "2.1.0" and len(sarif["runs"]) == 2


def test_score_of_a_failed_result_is_none():
    assert BatchResult("u", error="x").score is None
