"""OpenSSF Scorecard collector: only checks a shallow clone can't see, bounded severities."""

import httpx

from drrepo.agents.analysts.security import SecurityAnalyst
from drrepo.config import Config
from drrepo.recon.scorecard import collect_scorecard
from tests.conftest import mock_http, ok

URL = "GET api.securityscorecards.dev/projects/github.com/pallets/click"
# Trimmed from a real response (2026-11).
PAYLOAD = {
    "date": "2026-11-23",
    "repo": {"name": "github.com/pallets/click", "commit": "08b803cf32ce" + "0" * 28},
    "score": 7.3,
    "checks": [
        {
            "name": "Code-Review",
            "score": 8,
            "reason": "14/16 approved",
            "documentation": {"url": "https://scorecard.dev/#code-review"},
        },
        {
            "name": "Branch-Protection",
            "score": 3,
            "reason": "not maximal",
            "documentation": {"url": "https://scorecard.dev/#branch-protection"},
        },
        {
            "name": "Signed-Releases",
            "score": 0,
            "reason": "no signed releases",
            "documentation": {},
        },
        {"name": "Fuzzing", "score": -1, "reason": "inconclusive", "documentation": {}},
        # Overlaps DrRepo's own checks: ignored.
        {"name": "Dangerous-Workflow", "score": 0, "reason": "dangerous", "documentation": {}},
        {"name": "Vulnerabilities", "score": 0, "reason": "12 vulns", "documentation": {}},
    ],
}


def test_uses_only_non_overlapping_checks_and_maps_severity():
    result = collect_scorecard(
        "https://github.com/pallets/click", Config(), mock_http({URL: PAYLOAD})
    )
    assert result.status.value == "ok"
    assert {c["name"] for c in result.data["checks"]} == {
        "Code-Review",
        "Branch-Protection",
        "Signed-Releases",
        "Fuzzing",
    }
    found = {f["rule"]: f for f in result.data["findings"]}
    # Score 8 passes; -1 is inconclusive; 3 -> second tier; 0 -> first tier.
    assert set(found) == {"Branch-Protection", "Signed-Releases"}
    assert found["Branch-Protection"]["severity"] == "low"
    assert found["Signed-Releases"]["severity"] == "low"
    assert found["Branch-Protection"]["url"] == "https://scorecard.dev/#branch-protection"
    assert result.data["scanned_commit"].startswith("08b803cf32ce")


def test_unpublished_repositories_and_failures_degrade():
    missing = collect_scorecard(
        "https://github.com/pallets/click", Config(), mock_http({URL: httpx.Response(404)})
    )
    assert missing.status.value == "skipped" and "no OpenSSF Scorecard" in missing.detail
    broken = collect_scorecard(
        "https://github.com/pallets/click", Config(), mock_http({URL: httpx.Response(500)})
    )
    assert broken.status.value == "error" and "HTTP 500" in broken.detail
    disabled = collect_scorecard("https://github.com/pallets/click", Config(enable_scorecard=False))
    assert disabled.status.value == "skipped"


def test_scorecard_findings_count_on_the_bounded_curve():
    findings = collect_scorecard(
        "https://github.com/pallets/click", Config(), mock_http({URL: PAYLOAD})
    ).data["findings"]
    recon = {
        "security": ok({"findings": [], "tool_status": {"bandit": "ok"}}, name="security"),
        "scorecard": ok({"findings": findings}, name="scorecard"),
    }
    assessment = SecurityAnalyst().assess(recon)
    assert {i.source for i in assessment.issues} == {"scorecard"}
    assert 60 <= assessment.score < 100  # process findings never dominate code security


def test_scorecard_on_another_commit_is_noted():
    findings = collect_scorecard(
        "https://github.com/pallets/click", Config(), mock_http({URL: PAYLOAD})
    ).data
    recon = {
        "security": ok({"findings": [], "tool_status": {}}, name="security"),
        "scorecard": ok(findings, name="scorecard"),
        "repo_clone": ok({"commit_sha": "f" * 40}, name="repo_clone"),
    }
    notes = SecurityAnalyst().assess(recon).notes
    assert any("not the analyzed commit ffffffffffff" in n for n in notes)
