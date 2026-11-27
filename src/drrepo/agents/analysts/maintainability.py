"""Maintainability analyst: project hygiene and activity signals."""

from __future__ import annotations

from datetime import UTC, datetime

from drrepo.agents.analysts.base import (
    Analyst,
    Assessment,
    Recon,
    collector_data,
    decay_score,
    issue_penalty,
    sort_issues,
)
from drrepo.models import Category, Issue, Severity

STALE_DAYS = 365
_SCALE = 50.0


def _issue(
    severity: Severity, rule: str, title: str, description: str, recommendation: str
) -> Issue:
    return Issue(
        severity=severity,
        category=Category.MAINTAINABILITY,
        title=title,
        description=description,
        recommendation=recommendation,
        source="repo_hygiene",
        rule_id=rule,
    )


def days_since(iso_timestamp: str | None, now: datetime | None = None) -> int | None:
    if not iso_timestamp:
        return None
    try:
        then = datetime.fromisoformat(iso_timestamp)  # 3.11+ parses a trailing Z
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return ((now or datetime.now(UTC)) - then).days


class MaintainabilityAnalyst(Analyst):
    category = Category.MAINTAINABILITY
    tool_families = ("files", "git_history")
    rescore_scale = _SCALE

    def assess(self, recon: Recon) -> Assessment:
        layout = collector_data(recon, "repo_layout")
        github = collector_data(recon, "github_metadata")
        structure = (layout or {}).get("file_structure") or (github or {}).get("file_structure")
        if not structure:
            return self.unassessed(
                "Maintainability could not be assessed: neither the clone nor GitHub metadata was available."
            )

        github = github or {}
        stars = int(github.get("stars") or 0)
        issues: list[Issue] = []

        if github.get("archived"):
            issues.append(
                _issue(
                    Severity.HIGH,
                    "archived",
                    "Repository is archived",
                    "The owner has archived this repository; it is read-only and unmaintained.",
                    "Treat as unmaintained; look for an active fork or alternative.",
                )
            )
        if not structure.get("has_tests"):
            issues.append(
                _issue(
                    Severity.HIGH,
                    "no-tests",
                    "No automated tests found",
                    "No test directories or test files were detected.",
                    "Add an automated test suite and run it in CI.",
                )
            )
        elif layout and layout.get("source_file_count", 0) >= 20:
            ratio = layout.get("test_file_count", 0) / max(1, layout["source_file_count"])
            if ratio < 0.05:
                issues.append(
                    _issue(
                        Severity.LOW,
                        "thin-tests",
                        "Very few test files relative to source",
                        f"{layout.get('test_file_count', 0)} test files for {layout['source_file_count']} source files.",
                        "Grow test coverage for the core modules.",
                    )
                )
        if not structure.get("has_ci"):
            issues.append(
                _issue(
                    Severity.MEDIUM,
                    "no-ci",
                    "No CI configuration found",
                    "No GitHub Actions, GitLab CI, CircleCI, or similar config was found.",
                    "Add a CI pipeline that runs tests and lint on every push.",
                )
            )
        if not structure.get("has_license") and not github.get("license_spdx_id"):
            issues.append(
                _issue(
                    Severity.HIGH,
                    "no-license",
                    "No license",
                    "Without a license, nobody may legally reuse or redistribute the code.",
                    "Add a LICENSE file (e.g. MIT or Apache-2.0).",
                )
            )
        if not structure.get("has_contributing") and stars > 50:
            issues.append(
                _issue(
                    Severity.LOW,
                    "no-contributing",
                    "No contributing guide",
                    "No CONTRIBUTING file, despite community interest.",
                    "Add CONTRIBUTING.md explaining setup, tests, and the PR process.",
                )
            )
        if not structure.get("has_changelog") and stars > 100:
            issues.append(
                _issue(
                    Severity.LOW,
                    "no-changelog",
                    "No changelog",
                    "Users can't see what changed between releases.",
                    "Keep a CHANGELOG.md (see keepachangelog.com) or publish GitHub releases.",
                )
            )
        if layout and not structure.get("has_security_policy") and stars > 500:
            issues.append(
                _issue(
                    Severity.LOW,
                    "no-security-policy",
                    "No security policy",
                    "No SECURITY.md telling reporters how to disclose vulnerabilities privately.",
                    "Add SECURITY.md with a private reporting channel.",
                )
            )

        idle = days_since(github.get("pushed_at"))
        if idle is not None and idle > STALE_DAYS and not github.get("archived"):
            issues.append(
                _issue(
                    Severity.MEDIUM,
                    "inactive",
                    "Repository appears inactive",
                    f"Last push was {idle} days ago.",
                    "If the project is unmaintained, say so in the README; otherwise cut a release.",
                )
            )

        issues = sort_issues(issues)
        present = [k.removeprefix("has_").replace("_", " ") for k, v in structure.items() if v]
        summary = (
            f"Present: {', '.join(present) or 'none of the usual hygiene files'}. "
            + (f"Last push {idle} days ago. " if idle is not None else "")
            + (
                f"{len(issues)} maintainability issue(s)."
                if issues
                else "No maintainability issues."
            )
        )
        facts = (
            f"Structure: {structure}\nStars: {stars}; open issues: {github.get('open_issues', 'unknown')}; "
            f"archived: {github.get('archived', False)}; days since last push: {idle}\n"
            f"Test files: {(layout or {}).get('test_file_count', 'unknown')}; "
            f"source files: {(layout or {}).get('source_file_count', 'unknown')}\n"
            "Issues:\n" + "\n".join(f"- [{i.severity.value}] {i.title}" for i in issues)
        )
        return Assessment(
            issues=issues,
            score=decay_score(issue_penalty(issues), _SCALE),
            summary=summary,
            narrative_facts=facts,
        )
