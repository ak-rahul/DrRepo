"""Organization batch mode (`drrepo org <owner>`): audit many repositories, rank them.

Lists an organization's (or user's) public repositories through the GitHub API,
newest push first, leaving out archived repositories and forks unless asked.
Analyses run on a bounded thread pool over one `AnalysisService`, so the circuit
breaker and the dependency lookup cache are shared; each run still gets its own
token budget. A failed repository is a row in the leaderboard, never a failed
batch.

Outputs: a Markdown leaderboard, the same as JSON, and one SARIF log with a run
per repository (`aggregate_sarif`), for code scanning or a dashboard. Schedule it
(cron, a scheduled workflow) for weekly re-analysis; with score history on, the
leaderboard shows each repository's change since the previous run.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from drrepo.config import Config
from drrepo.log import logger
from drrepo.report.exporters import to_sarif
from drrepo.report.synthesis import grade

if TYPE_CHECKING:
    from collections.abc import Callable

    from drrepo.service import AnalysisService

GITHUB_API = "https://api.github.com"
MAX_REPOSITORIES = 200
_PAGE_SIZE = 100


class RepositoryListError(Exception):
    """The owner's repositories couldn't be listed (unknown owner, rate limit, network)."""


@dataclass
class BatchResult:
    url: str
    report: dict[str, Any] | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float | None:
        return float(self.report["overall_score"]) if self.report else None


def _pages(
    client: httpx.Client, owner: str, kind: str, headers: dict[str, str], wanted: int
) -> list[dict[str, Any]] | None:
    """Every repository page for `owner` as an org or a user; None if it isn't one."""
    repos: list[dict[str, Any]] = []
    page = 1
    while len(repos) < wanted:
        response = client.get(
            f"{GITHUB_API}/{kind}/{owner}/repos",
            params={
                "type": "public" if kind == "orgs" else "owner",
                "sort": "pushed",
                "per_page": _PAGE_SIZE,
                "page": page,
            },
            headers=headers,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            hint = " (rate limited; set GH_TOKEN)" if response.status_code in (403, 429) else ""
            raise RepositoryListError(
                f"GitHub API {response.status_code} listing {owner}'s repositories{hint}"
            )
        batch = response.json()
        repos += batch
        if len(batch) < _PAGE_SIZE:
            break
        page += 1
    return repos


def list_repositories(
    owner: str,
    config: Config,
    *,
    limit: int = 20,
    include_forks: bool = False,
    include_archived: bool = False,
    http_client: httpx.Client | None = None,
) -> list[str]:
    """Public repository URLs of an organization (or, failing that, a user), newest push first."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "drrepo"}
    if config.github_token:
        headers["Authorization"] = f"Bearer {config.github_token}"
    limit = max(1, min(limit, MAX_REPOSITORIES))
    client = http_client or httpx.Client(timeout=30)
    try:
        # Forks and archived repositories are filtered after listing, so fetch spare pages.
        repos = _pages(client, owner, "orgs", headers, limit * 3)
        if repos is None:
            repos = _pages(client, owner, "users", headers, limit * 3)
    except httpx.HTTPError as e:
        raise RepositoryListError(f"could not reach the GitHub API: {e}") from e
    finally:
        if http_client is None:
            client.close()
    if repos is None:
        raise RepositoryListError(f"no GitHub organization or user named {owner!r}")
    urls = [
        str(r["html_url"])
        for r in repos
        if not r.get("private")
        and (include_forks or not r.get("fork"))
        and (include_archived or not r.get("archived"))
    ]
    return urls[:limit]


def run_batch(
    service: AnalysisService,
    urls: list[str],
    *,
    workers: int = 2,
    deep: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[BatchResult]:
    """Analyze every URL, `workers` at a time. Results keep the input order."""

    def one(url: str) -> BatchResult:
        if progress:
            progress(f"Analyzing {url}")
        try:
            report = service.analyze(url, deep=deep)
        except Exception as e:  # one repository never fails the batch
            logger.warning(f"Batch: {url} failed: {type(e).__name__}: {e}")
            return BatchResult(url, error=f"{type(e).__name__}: {e}")
        if progress:
            progress(f"Finished {url}: {report.get('overall_score')}")
        return BatchResult(url, report=report)

    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="drrepo-batch") as pool:
        return list(pool.map(one, urls))


def leaderboard(results: list[BatchResult]) -> list[dict[str, Any]]:
    """One row per repository, best score first; failures last."""
    rows = []
    for r in results:
        report = r.report or {}
        counts = report.get("issue_counts") or {}
        delta = (report.get("score_history") or {}).get("overall_score_delta")
        rows.append(
            {
                "repository": (report.get("repository") or {}).get("name") or r.url,
                "url": r.url,
                "score": r.score,
                "grade": grade(r.score) if r.score is not None else None,
                "delta": delta,
                "critical": counts.get("critical", 0),
                "high": counts.get("high", 0),
                "categories": {
                    name: cs.get("score") if cs.get("assessed", True) else None
                    for name, cs in (report.get("category_scores") or {}).items()
                },
                "error": r.error,
            }
        )
    return sorted(rows, key=lambda row: (row["score"] is None, -(row["score"] or 0.0)))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def leaderboard_markdown(owner: str, rows: list[dict[str, Any]]) -> str:
    categories = sorted({c for row in rows for c in row["categories"]})
    header = ["#", "Repository", "Score", "Change", "Critical", "High"] + [
        c.replace("_", " ").title() for c in categories
    ]
    lines = [
        f"# DrRepo leaderboard: {_cell(owner)}",
        "",
        f"{sum(r['score'] is not None for r in rows)} of {len(rows)} repositories analyzed.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for rank, row in enumerate(rows, 1):
        if row["score"] is None:
            lines.append(
                f"| {rank} | {_cell(row['repository'])} | failed: {_cell(str(row['error']))[:120]} |"
                + " |" * (len(header) - 3)
            )
            continue
        delta = f"{row['delta']:+.1f}" if isinstance(row["delta"], (int, float)) else ""
        scores = [
            f"{row['categories'][c]:.0f}"
            if isinstance(row["categories"].get(c), (int, float))
            else "n/a"
            for c in categories
        ]
        lines.append(
            f"| {rank} | [{_cell(row['repository'])}]({row['url']}) | {row['score']:.1f} ({row['grade']}) "
            f"| {delta} | {row['critical']} | {row['high']} | " + " | ".join(scores) + " |"
        )
    return "\n".join(lines) + "\n"


def aggregate_sarif(reports: list[dict[str, Any]]) -> str:
    """One SARIF 2.1.0 log with a run per repository."""
    runs = [run for report in reports for run in json.loads(to_sarif(report)).get("runs", [])]
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": runs,
        },
        indent=2,
    )
