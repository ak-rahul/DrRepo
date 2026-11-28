"""Dependency analyst: known vulnerabilities (OSV.dev), pinning, license policy or
compatibility, and upstream maintenance (deprecated or long-unreleased packages)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from drrepo.agents.analysts.base import (
    Analyst,
    Assessment,
    Recon,
    collector_data,
    collector_detail,
    decay_score,
    issue_penalty,
    sort_issues,
)
from drrepo.models import Category, Issue, Severity

_SCALE = 40.0
# A runtime dependency with no release for this long is likely unmaintained.
STALE_RELEASE_DAYS = 730

# SPDX ids grouped by how they interact with a permissively licensed project.
# A heuristic, not legal advice -- see `license_issues`.
PERMISSIVE_LICENSES = {
    "MIT",
    "MIT-0",
    "APACHE-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "ISC",
    "PYTHON-2.0",
    "PSF-2.0",
    "UNLICENSE",
    "0BSD",
    "CC0-1.0",
    "ZLIB",
    "BSL-1.0",
}
STRONG_COPYLEFT_LICENSES = {
    "GPL-2.0",
    "GPL-2.0-ONLY",
    "GPL-2.0-OR-LATER",
    "GPL-3.0",
    "GPL-3.0-ONLY",
    "GPL-3.0-OR-LATER",
    "AGPL-3.0",
    "AGPL-3.0-ONLY",
    "AGPL-3.0-OR-LATER",
}


def license_category(spdx_id: str | None) -> str:
    if not spdx_id:
        return "unknown"
    normalized = spdx_id.strip().upper()
    if normalized in STRONG_COPYLEFT_LICENSES:
        return "strong_copyleft"
    if normalized in PERMISSIVE_LICENSES:
        return "permissive"
    return "unknown"


def _version_key(version: str) -> tuple[Any, ...]:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", version))


def _max_version(versions: list[str]) -> str | None:
    try:
        return max(versions, key=_version_key) if versions else None
    except TypeError:  # mixed int/str segments that don't compare cleanly
        return max(versions)


DEV_DOWNGRADE = {
    Severity.CRITICAL: Severity.MEDIUM,
    Severity.HIGH: Severity.LOW,
    Severity.MEDIUM: Severity.LOW,
    Severity.LOW: Severity.LOW,
}


def vulnerability_issues(vulns: list[dict[str, Any]]) -> list[Issue]:
    """One issue per vulnerable package version, at the severity of its worst advisory."""
    by_package: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for v in vulns:
        by_package[(v["ecosystem"], v["package"], v["version"])].append(v)

    issues = []
    for (ecosystem, package, version), items in by_package.items():
        # Advisories without a severity rating are treated as high: unknown is not safe.
        severities = [Severity.parse(v.get("severity"), default=Severity.HIGH) for v in items]
        worst = min(severities, key=lambda s: s.rank)
        dev_only = all(v.get("dev") for v in items)
        if dev_only:
            # Development tooling (test runners, linters, docs builders) doesn't ship
            # to users, so its advisories are rarely exploitable: drop two levels.
            worst = DEV_DOWNGRADE[worst]
        fixed = _max_version([f for v in items for f in v.get("fixed_versions", [])])
        listing = "; ".join(
            f"{v['vuln_id']}" + (f" ({v['summary'][:90]})" if v.get("summary") else "")
            for v in items[:5]
        )
        more = f"; and {len(items) - 5} more" if len(items) > 5 else ""
        kind = "development-only " if dev_only else ""
        imported: list[int] = [
            int(v["imported_in"]) for v in items if v.get("imported_in") is not None
        ]
        if imported and max(imported) > 0:
            evidence = f" Imported directly in {max(imported)} source file(s)."
        elif imported:
            evidence = (
                " Not imported directly by this repository's source: likely a transitive "
                "dependency, still reachable through whatever depends on it."
            )
        else:
            evidence = ""
        issues.append(
            Issue(
                severity=worst,
                category=Category.DEPENDENCIES,
                title=f"{package}@{version}: {len(items)} known vulnerabilit{'y' if len(items) == 1 else 'ies'}"
                + (" (dev)" if dev_only else ""),
                description=f"{kind}{ecosystem} package {package} {version} is affected by {listing}{more}.{evidence}",
                recommendation=(
                    f"Upgrade {package} to {fixed} or later."
                    if fixed
                    else f"Upgrade {package} past {version}."
                )
                + f" Details: https://osv.dev/vulnerability/{items[0]['vuln_id']}",
                source="osv.dev",
                rule_id=items[0]["vuln_id"],
                occurrences=1,
            )
        )
    return issues


def license_policy_issues(
    licenses: list[dict[str, Any]], deny: tuple[str, ...], allow: tuple[str, ...]
) -> list[Issue]:
    """Violations of an explicit license policy (LICENSE_DENY / LICENSE_ALLOW)."""
    denied = {d.lower() for d in deny}
    allowed = {a.lower() for a in allow}
    issues = []
    for lic in licenses:
        spdx = lic.get("license")
        if not spdx:
            continue
        if spdx.lower() in denied:
            severity, rule, why = Severity.HIGH, "license-denied", "is on the deny list"
        elif allowed and spdx.lower() not in allowed:
            severity, rule, why = Severity.MEDIUM, "license-not-allowed", "is not on the allow list"
        else:
            continue
        issues.append(
            Issue(
                severity=severity,
                category=Category.DEPENDENCIES,
                title=f"{lic['package']}: license {spdx} {why}",
                description=f"{lic['package']}@{lic['version']} ({lic['ecosystem']}) is licensed {spdx}, which {why} of this audit's license policy.",
                recommendation=f"Replace {lic['package']}, obtain an exception, or update the policy.",
                source="license-policy",
                rule_id=rule,
            )
        )
    return issues


def license_issues(licenses: list[dict[str, Any]], repo_license_spdx: str | None) -> list[Issue]:
    """Flag dependency licenses that may conflict with the repository's own license.

    Only a permissively licensed repository has a well-understood risk from a
    strong-copyleft dependency; anything else needs case-by-case legal judgment
    this heuristic can't automate, so it stays silent there.
    """
    if license_category(repo_license_spdx) != "permissive":
        return []

    issues = []
    for lic in licenses:
        if license_category(lic.get("license")) != "strong_copyleft":
            continue
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.DEPENDENCIES,
                title=f"{lic['package']}: {lic['license']} dependency in a {repo_license_spdx} project",
                description=(
                    f"{lic['package']}@{lic['version']} is licensed {lic['license']} (strong "
                    f"copyleft) while this repository is {repo_license_spdx}. Depending on how it is "
                    "used and distributed, this may create obligations for downstream users."
                ),
                recommendation=(
                    "Have this reviewed manually: automated scanning can't tell how the dependency is "
                    "linked or distributed, which changes the actual obligations. Not legal advice."
                ),
                source="license-audit",
                rule_id="copyleft-in-permissive",
            )
        )

    unknown = sum(1 for lic in licenses if lic.get("license") is None)
    if unknown >= 3:
        issues.append(
            Issue(
                severity=Severity.LOW,
                category=Category.DEPENDENCIES,
                title=f"{unknown} dependencies have an undeterminable license",
                description="deps.dev had no license metadata for these packages, so they weren't checked.",
                recommendation="Verify these licenses manually if compliance matters for this project.",
                source="license-audit",
                rule_id="unknown-license",
            )
        )
    return issues


def maintenance_issues(entries: list[dict[str, Any]]) -> list[Issue]:
    """Deprecated runtime packages (one issue each) and long-unreleased ones (one issue).

    "No release in two years" is a signal, not proof: small, finished libraries
    can be stable for years. So stale packages share one low-severity issue.
    """
    issues = []
    for entry in entries:
        if not entry.get("deprecated"):
            continue
        reason = str(entry.get("deprecated_reason") or "").strip()
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.DEPENDENCIES,
                title=f"{entry['package']}@{entry['version']} is deprecated upstream",
                description=(
                    f"The {entry['ecosystem']} registry marks {entry['package']}@{entry['version']} "
                    "as deprecated" + (f": {reason}" if reason else ".")
                ),
                recommendation=(
                    f"Replace {entry['package']} with a maintained alternative"
                    + (
                        f", or upgrade if {entry['latest_version']} is not deprecated."
                        if entry.get("latest_version")
                        and entry.get("latest_version") != entry.get("version")
                        else "."
                    )
                ),
                source="dependency-maintenance",
                rule_id="deprecated-package",
            )
        )
    stale = sorted(
        (
            e
            for e in entries
            if not e.get("deprecated")
            and isinstance(e.get("days_since_release"), int)
            and e["days_since_release"] > STALE_RELEASE_DAYS
        ),
        key=lambda e: -int(e["days_since_release"]),
    )
    if stale:
        listed = ", ".join(
            f"{e['package']} ({str(e.get('last_release') or '')[:7]})" for e in stale[:8]
        )
        issues.append(
            Issue(
                severity=Severity.LOW,
                category=Category.DEPENDENCIES,
                title=(
                    f"{len(stale)} runtime "
                    + ("dependency has" if len(stale) == 1 else "dependencies have")
                    + " had no release in over 2 years"
                ),
                description=(
                    f"Newest release per package (year-month): {listed}"
                    + ("..." if len(stale) > 8 else "")
                    + ". Long-unreleased packages may be unmaintained, so security fixes may "
                    "never arrive. Small, finished libraries can also be stable for years."
                ),
                recommendation=(
                    "Check each upstream for activity, and plan replacements for packages "
                    "that are unmaintained."
                ),
                source="dependency-maintenance",
                rule_id="stale-package",
            )
        )
    return issues


class DependencyAnalyst(Analyst):
    category = Category.DEPENDENCIES
    tool_families = ("files", "dependencies")
    rescore_scale = _SCALE

    def assess(self, recon: Recon) -> Assessment:
        deps = collector_data(recon, "dependency_audit")
        if deps is None:
            detail = collector_detail(recon, "dependency_audit", "the audit did not run")
            return self.unassessed(f"Dependency health is unknown: {detail}.")

        checked = int(deps.get("packages_checked", 0))
        unpinned: list[str] = deps.get("unpinned", [])
        manifests: list[str] = deps.get("manifests", [])
        repo_license = (collector_data(recon, "github_metadata") or {}).get("license_spdx_id")
        has_lockfile = (
            (collector_data(recon, "repo_layout") or {}).get("file_structure") or {}
        ).get("has_lockfile")

        if not manifests:
            return Assessment(
                issues=[],
                score=100.0,
                summary="No supported dependency manifests (Python/npm) were found.",
            )

        vuln_issues = vulnerability_issues(deps.get("vulnerabilities", []))
        licenses = deps.get("licenses", [])
        # The policy travels in the collector's data (it is per-run config), not on the analyst.
        policy = deps.get("license_policy") or {}
        deny, allow = tuple(policy.get("deny", ())), tuple(policy.get("allow", ()))
        issues = (
            vuln_issues
            + (
                license_policy_issues(licenses, deny, allow)
                if deny or allow
                else license_issues(licenses, repo_license)
            )
            + maintenance_issues(deps.get("maintenance", []))
        )
        if unpinned and not has_lockfile:
            issues.append(
                Issue(
                    severity=Severity.MEDIUM if checked == 0 else Severity.LOW,
                    category=self.category,
                    title=f"{len(unpinned)} dependencies have no exact version and no lockfile",
                    description=(
                        f"Declared as ranges with no lockfile ({', '.join(unpinned[:8])}"
                        f"{'...' if len(unpinned) > 8 else ''}), so installs aren't reproducible and "
                        "these packages could not be checked for known vulnerabilities."
                    ),
                    recommendation="Commit a lockfile (uv.lock, poetry.lock, package-lock.json) or pin exact versions.",
                    source="dependency_audit",
                    rule_id="unpinned-dependencies",
                )
            )
        issues = sort_issues(issues)

        summary = (
            f"Checked {checked} exactly-versioned dependencies "
            f"({int(deps.get('dev_packages', 0))} development-only) from {len(manifests)} manifest(s): "
            f"{len(vuln_issues)} vulnerable package version(s)"
            + (
                f" ({sum(1 for i in vuln_issues if i.title.endswith('(dev)'))} in dev tooling)"
                if vuln_issues
                else ""
            )
            + (f", {len(unpinned)} unpinned" if unpinned else "")
            + "."
        )
        facts = None
        if issues:
            facts = (
                f"{summary}\nRepository license: {repo_license or 'unspecified'}\nIssues:\n"
                + "\n".join(f"- [{i.severity.value}] {i.title}" for i in issues[:12])
            )
        return Assessment(
            issues=issues,
            score=decay_score(issue_penalty(issues), _SCALE),
            summary=summary,
            narrative_facts=facts,
        )
