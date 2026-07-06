"""Dependency analyst: turns OSV.dev vulnerability hits and deps.dev license data
into issues + a narrative."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker

_SYSTEM_PROMPT = """You are a dependency security specialist. Write a concise, honest \
narrative (2-4 sentences) about the dependency health of a repository given a list of \
known vulnerabilities in its declared packages and any license compatibility concerns. Do \
not invent vulnerabilities or licenses that weren't given to you."""

# SPDX identifiers, grouped by how they typically interact with a permissively
# licensed project. This is a heuristic, not legal advice -- see `_license_issues`.
_PERMISSIVE_LICENSES = {
    "MIT",
    "APACHE-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "ISC",
    "PYTHON-2.0",
    "UNLICENSE",
    "0BSD",
    "CC0-1.0",
    "ZLIB",
    "BSL-1.0",
}
_STRONG_COPYLEFT_LICENSES = {
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


def _license_category(spdx_id: Optional[str]) -> str:
    if not spdx_id:
        return "unknown"
    normalized = spdx_id.strip().upper()
    if normalized in _STRONG_COPYLEFT_LICENSES:
        return "strong_copyleft"
    if normalized in _PERMISSIVE_LICENSES:
        return "permissive"
    return "unknown"


def _license_issues(
    licenses: List[Dict[str, Any]], repo_license_spdx: Optional[str]
) -> List[Issue]:
    """Flag dependency licenses that may conflict with the repository's own license.

    Only a permissively-licensed repository has a well-understood compatibility
    risk from a strong-copyleft dependency; anything else needs case-by-case
    legal judgment this heuristic can't automate, so it stays silent there.
    """
    if _license_category(repo_license_spdx) != "permissive":
        return []

    issues = []
    for lic in licenses:
        if _license_category(lic.get("license")) != "strong_copyleft":
            continue
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.DEPENDENCIES,
                title=f"{lic['package']}: {lic['license']} dependency in a {repo_license_spdx}-licensed project",
                description=(
                    f"{lic['package']}@{lic['version']} is licensed under {lic['license']}, a "
                    f"strong copyleft license, while this repository is licensed under "
                    f"{repo_license_spdx}. Depending on how this dependency is used, this may "
                    "create license compliance obligations for downstream users."
                ),
                recommendation=(
                    "Have this reviewed manually -- automated scanning can't determine whether "
                    f"{lic['package']} is statically linked, dynamically linked, or invoked as a "
                    "separate process, which changes the actual compliance risk."
                ),
                source="license-audit",
            )
        )

    unknown_count = sum(1 for lic in licenses if lic.get("license") is None)
    if unknown_count >= 3:
        issues.append(
            Issue(
                severity=Severity.LOW,
                category=Category.DEPENDENCIES,
                title=f"{unknown_count} dependencies have an undeterminable license",
                description=(
                    "License metadata could not be retrieved from deps.dev for these packages, "
                    f"so they weren't checked for compatibility with this project's "
                    f"{repo_license_spdx} license."
                ),
                recommendation="Verify these dependencies' licenses manually if compliance matters for this project.",
                source="license-audit",
            )
        )
    return issues


def _vulns_to_issues(vulnerabilities: list[dict]) -> list[Issue]:
    issues = []
    for v in vulnerabilities:
        vuln_id = v["vuln_id"]
        package = v["package"]
        version = v["version"]
        issues.append(
            Issue(
                severity=Severity.HIGH,
                category=Category.DEPENDENCIES,
                title=f"{package}@{version}: {vuln_id}",
                description=f"Known vulnerability {vuln_id} affects {package} {version}.",
                recommendation=(
                    f"Upgrade {package} past {version}. "
                    f"Details: https://osv.dev/vulnerability/{vuln_id}"
                ),
                source="osv.dev",
            )
        )
    return issues


def _score(issues: list[Issue], packages_checked: int) -> float:
    if packages_checked == 0:
        return 100.0
    penalty = min(len(issues) * 8, 90)
    return max(0.0, 100.0 - penalty)


class DependencyAnalyst(BaseAnalystAgent):
    def __init__(
        self,
        llm_client: LLMClient,
        llm_breaker: Optional[CircuitBreaker] = None,
        llm_budget: Optional[LLMBudgetTracker] = None,
    ):
        super().__init__(
            "DependencyAnalyst",
            _SYSTEM_PROMPT,
            llm_client,
            llm_breaker=llm_breaker,
            llm_budget=llm_budget,
        )

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        dep_data = collector_results.get("dependency_audit", {})

        if "packages_checked" not in dep_data:
            # The collector always sets this key on a real run (even a
            # genuine zero-manifest repo gets `packages_checked: 0`
            # explicitly) -- its absence means the audit itself failed
            # (e.g. OSV.dev lookup error) or never ran, which must not be
            # reported as a clean "no dependencies" pass.
            return {
                "summary": "Dependency audit could not be completed (the vulnerability lookup "
                "failed or was skipped), so dependency health is unknown rather than clean.",
                "score": 50.0,
                "issues": [],
            }

        vulnerabilities = dep_data.get("vulnerabilities", [])
        licenses = dep_data.get("licenses", [])
        packages_checked = dep_data.get("packages_checked", 0)
        repo_license_spdx = collector_results.get("github_metadata", {}).get("license_spdx_id")

        vuln_issues = _vulns_to_issues(vulnerabilities)
        license_issues = _license_issues(licenses, repo_license_spdx)
        issues = vuln_issues + license_issues
        score = _score(issues, packages_checked)

        if packages_checked == 0:
            return {
                "summary": "No dependency manifest files were found to audit.",
                "score": score,
                "issues": [],
            }
        if not issues:
            return {
                "summary": (
                    f"Checked {packages_checked} dependencies against OSV.dev; no known "
                    "vulnerabilities or license concerns found."
                ),
                "score": score,
                "issues": [],
            }

        prompt = (
            f"Checked {packages_checked} dependencies against OSV.dev and cross-checked "
            f"licenses against this repository's {repo_license_spdx or 'unspecified'} license.\n"
            f"Found {len(vuln_issues)} known vulnerabilities: {[i.title for i in vuln_issues[:10]]}\n"
            f"Found {len(license_issues)} license concerns: {[i.title for i in license_issues[:5]]}\n\n"
            "Summarize the dependency health of this repository, covering both vulnerabilities "
            "and license risk."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
