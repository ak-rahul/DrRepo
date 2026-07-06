"""Security analyst: turns bandit/secret-scan findings into issues + a narrative."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker

_SYSTEM_PROMPT = """You are a security engineer reviewing static analysis results for a \
repository. Write a concise, honest narrative (3-5 sentences) about the security posture. \
Do not invent findings that weren't given to you, and don't be alarmist about low-severity \
issues."""

_BANDIT_SEVERITY_MAP = {"HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW}


def _findings_to_issues(findings: list[dict]) -> list[Issue]:
    issues = []
    for f in findings:
        if f["tool"] == "secret_scan":
            severity = Severity.CRITICAL
        else:  # bandit
            severity = _BANDIT_SEVERITY_MAP.get((f.get("severity") or "").upper(), Severity.MEDIUM)

        issues.append(
            Issue(
                severity=severity,
                category=Category.SECURITY,
                title=f"{f['tool']}: {f.get('rule', 'finding')}",
                description=f.get("message") or "No message provided",
                recommendation=(
                    "Remove the committed secret and rotate it immediately"
                    if f["tool"] == "secret_scan"
                    else f"Review and fix the {f.get('rule', 'issue')} flagged by bandit"
                ),
                file=f.get("file"),
                line=f.get("line"),
                source=f["tool"],
            )
        )
    return issues


def _score(issues: list[Issue]) -> float:
    if not issues:
        return 100.0
    penalty = sum(
        {"critical": 30, "high": 15, "medium": 6, "low": 2}[i.severity.value] for i in issues
    )
    return max(0.0, 100.0 - penalty)


class SecurityAnalyst(BaseAnalystAgent):
    def __init__(
        self,
        llm_client: LLMClient,
        llm_breaker: Optional[CircuitBreaker] = None,
        llm_budget: Optional[LLMBudgetTracker] = None,
    ):
        super().__init__(
            "SecurityAnalyst",
            _SYSTEM_PROMPT,
            llm_client,
            llm_breaker=llm_breaker,
            llm_budget=llm_budget,
        )

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        security_data = collector_results.get("security", {})
        findings = security_data.get("findings", [])
        tool_status = security_data.get("tool_status", {})

        issues = _findings_to_issues(findings)
        score = _score(issues)

        if not findings:
            return {
                "summary": "No security issues were found by static analysis or secret scanning.",
                "score": score,
                "issues": [],
            }

        secret_count = sum(1 for i in issues if i.source == "secret_scan")
        prompt = (
            f"Security scan found {len(issues)} issues "
            f"({secret_count} possible committed secrets).\n"
            f"Tool status: {tool_status}\n"
            f"Sample findings: {[i.title for i in issues[:10]]}\n\n"
            "Summarize the security posture of this repository."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
