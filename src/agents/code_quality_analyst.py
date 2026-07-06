"""Code Quality analyst: turns ruff/semgrep findings into issues + a narrative.

Issues are built deterministically from collector findings (file/line/rule
come straight from the tool, never from LLM text) -- the LLM's only job is to
summarize and call out the highest-impact patterns.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Optional

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.llm_budget import LLMBudgetTracker

_SYSTEM_PROMPT = """You are a senior code reviewer. You will be given a summary of static \
analysis findings (from ruff and semgrep) for a repository. Write a concise, honest \
narrative (3-5 sentences) describing the overall code quality, calling out the most \
common or impactful patterns. Do not invent findings that weren't given to you."""

_SEMGREP_SEVERITY_MAP = {"ERROR": Severity.HIGH, "WARNING": Severity.MEDIUM, "INFO": Severity.LOW}


def _findings_to_issues(findings: list[dict]) -> list[Issue]:
    issues = []
    for f in findings:
        if f["tool"] == "semgrep":
            severity = _SEMGREP_SEVERITY_MAP.get((f.get("severity") or "").upper(), Severity.MEDIUM)
        else:  # ruff findings don't carry a severity; treat as medium-priority style/bug issues
            severity = Severity.MEDIUM

        issues.append(
            Issue(
                severity=severity,
                category=Category.CODE_QUALITY,
                title=f"{f['tool']}: {f.get('rule', 'finding')}",
                description=f.get("message") or "No message provided",
                recommendation=f"Fix the {f.get('rule', 'issue')} flagged by {f['tool']}",
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
        {"critical": 15, "high": 10, "medium": 4, "low": 1}[i.severity.value] for i in issues
    )
    return max(0.0, 100.0 - penalty)


class CodeQualityAnalyst(BaseAnalystAgent):
    def __init__(
        self,
        llm_client: LLMClient,
        llm_breaker: Optional[CircuitBreaker] = None,
        llm_budget: Optional[LLMBudgetTracker] = None,
    ):
        super().__init__(
            "CodeQualityAnalyst",
            _SYSTEM_PROMPT,
            llm_client,
            llm_breaker=llm_breaker,
            llm_budget=llm_budget,
        )

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        static = collector_results.get("static_analysis", {})
        findings = static.get("findings", [])
        tool_status = static.get("tool_status", {})

        issues = _findings_to_issues(findings)
        score = _score(issues)

        if not findings:
            summary = "No static analysis findings were available for this repository."
            if any("skipped" in v or "disabled" in v for v in tool_status.values()):
                summary += f" ({tool_status})"
            return {"summary": summary, "score": score, "issues": []}

        rule_counts = Counter(i.title for i in issues)
        top_rules = ", ".join(f"{rule} ({count}x)" for rule, count in rule_counts.most_common(5))
        prompt = (
            f"Static analysis found {len(issues)} issues across the repository.\n"
            f"Most common: {top_rules}\n"
            f"Tool status: {tool_status}\n\n"
            "Summarize the code quality state of this repository."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
