"""Dependency analyst: turns OSV.dev vulnerability hits into issues + a narrative."""

from __future__ import annotations

from typing import Any, Dict

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict

_SYSTEM_PROMPT = """You are a dependency security specialist. Write a concise, honest \
narrative (2-4 sentences) about the dependency health of a repository given a list of \
known vulnerabilities in its declared packages. Do not invent vulnerabilities that weren't \
given to you."""


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
    def __init__(self, llm_client: LLMClient):
        super().__init__("DependencyAnalyst", _SYSTEM_PROMPT, llm_client)

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        dep_data = collector_results.get("dependency_audit", {})
        vulnerabilities = dep_data.get("vulnerabilities", [])
        packages_checked = dep_data.get("packages_checked", 0)

        issues = _vulns_to_issues(vulnerabilities)
        score = _score(issues, packages_checked)

        if packages_checked == 0:
            return {
                "summary": "No dependency manifest files were found to audit.",
                "score": score,
                "issues": [],
            }
        if not vulnerabilities:
            return {
                "summary": f"Checked {packages_checked} dependencies against OSV.dev; no known vulnerabilities found.",
                "score": score,
                "issues": [],
            }

        prompt = (
            f"Checked {packages_checked} dependencies against OSV.dev.\n"
            f"Found {len(vulnerabilities)} known vulnerabilities: "
            f"{[i.title for i in issues[:10]]}\n\n"
            "Summarize the dependency health of this repository."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
