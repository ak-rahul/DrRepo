"""OpenSSF Scorecard signals a shallow clone can't see.

Scorecard (https://scorecard.dev) publishes weekly automated checks for about a
million popular repositories. Several of them need history or GitHub settings
that DrRepo's shallow clone doesn't have, so they add real signal:

    Branch-Protection, Code-Review, Signed-Releases, Binary-Artifacts, Fuzzing, SAST

The rest overlap checks DrRepo already runs on the analyzed commit itself
(zizmor for workflows and pinning, OSV.dev for vulnerabilities, the layout scan
for license and security policy) and are skipped, so nothing is counted twice.

Scorecard describes the default branch at its last scan, not necessarily the
commit DrRepo analyzed; `data.scanned_commit` and `data.date` say which.

data (status OK):
    score: float (0-10), date: str, scanned_commit: str | None,
    checks: [{name, score, reason, url}]     # the used checks only; score -1 = inconclusive
    findings: [{tool, rule, message, severity, file, line, url, category}]
"""

from __future__ import annotations

from typing import Any

import httpx

from drrepo.config import Config
from drrepo.models import CollectorResult, CollectorStatus, RepoRef

NAME = "scorecard"
API_URL = "https://api.securityscorecards.dev/projects/github.com/{full_name}"

# Check -> (severity at score 0-2, severity at score 3-5). Scores >= 6 are fine.
USED_CHECKS: dict[str, tuple[str, str]] = {
    "Branch-Protection": ("medium", "low"),
    "Code-Review": ("medium", "low"),
    "Signed-Releases": ("low", "low"),
    "Binary-Artifacts": ("medium", "low"),
    "Fuzzing": ("low", "low"),
    "SAST": ("low", "low"),
}


def _findings(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for check in checks:
        name, score = check["name"], check["score"]
        if score < 0 or score >= 6:  # -1: inconclusive (e.g. no releases to sign)
            continue
        severity = USED_CHECKS[name][0 if score <= 2 else 1]
        findings.append(
            {
                "tool": "scorecard",
                "rule": name,
                "message": f"OpenSSF Scorecard {name}: {score}/10. {check['reason']}",
                "severity": severity,
                "file": None,
                "line": None,
                "url": check.get("url"),
                "category": "security",
            }
        )
    return findings


def collect_scorecard(
    repo_url: str, config: Config, http_client: httpx.Client | None = None
) -> CollectorResult:
    """Fetch the published Scorecard. `http_client` is injectable for tests."""
    if not config.enable_scorecard:
        return CollectorResult.skipped(NAME, "disabled by config")
    try:
        repo = RepoRef.parse(repo_url)
    except ValueError as e:
        return CollectorResult(NAME, CollectorStatus.ERROR, detail=str(e))
    client = http_client or httpx.Client(
        timeout=config.collector_timeout_seconds, headers={"User-Agent": "drrepo"}
    )
    try:
        resp = client.get(API_URL.format(full_name=repo.full_name))
    except httpx.HTTPError as e:
        return CollectorResult(
            NAME, CollectorStatus.ERROR, detail=f"Scorecard API unreachable: {e}"
        )
    finally:
        if http_client is None:
            client.close()
    if resp.status_code == 404:
        return CollectorResult.skipped(NAME, "no OpenSSF Scorecard published for this repository")
    if resp.status_code != 200:
        return CollectorResult(
            NAME, CollectorStatus.ERROR, detail=f"Scorecard API returned HTTP {resp.status_code}"
        )
    try:
        payload = resp.json()
        checks = [
            {
                "name": c["name"],
                "score": int(c.get("score", -1)),
                "reason": str(c.get("reason") or ""),
                "url": (c.get("documentation") or {}).get("url"),
            }
            for c in payload.get("checks", [])
            if c.get("name") in USED_CHECKS
        ]
    except (ValueError, KeyError, TypeError) as e:
        return CollectorResult(
            NAME, CollectorStatus.ERROR, detail=f"unexpected Scorecard response: {e}"
        )
    return CollectorResult(
        NAME,
        CollectorStatus.OK,
        data={
            "score": payload.get("score"),
            "date": payload.get("date"),
            "scanned_commit": (payload.get("repo") or {}).get("commit"),
            "checks": checks,
            "findings": _findings(checks),
        },
    )
