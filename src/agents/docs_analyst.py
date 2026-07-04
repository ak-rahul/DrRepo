"""Documentation analyst: README completeness/quality, deterministic issues + LLM narrative."""

from __future__ import annotations

from typing import Any, Dict

from src.agents.base import BaseAnalystAgent, LLMClient
from src.models import Category, Issue, Severity, issue_to_dict

_SYSTEM_PROMPT = """You are a technical writing expert. Given structured facts about a \
repository's README (word count, missing sections, quality score) and a short excerpt, \
write a concise, honest narrative (3-5 sentences) about its documentation quality and the \
single highest-impact improvement to make first. Do not invent facts you weren't given."""

_CRITICAL_SECTIONS = {"Installation", "Usage", "License"}


def _readme_issues(readme_data: Dict[str, Any]) -> list[Issue]:
    issues = []
    for section in readme_data.get("missing_sections", []):
        severity = Severity.HIGH if section in _CRITICAL_SECTIONS else Severity.MEDIUM
        issues.append(
            Issue(
                severity=severity,
                category=Category.DOCUMENTATION,
                title=f"Missing '{section}' section",
                description=f"The README does not appear to have a {section} section.",
                recommendation=f"Add a {section} section to the README.",
                file="README.md",
                source="readme_analyzer",
            )
        )

    if readme_data.get("word_count", 0) < 300:
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.DOCUMENTATION,
                title="README is too short",
                description=f"README has only {readme_data.get('word_count', 0)} words.",
                recommendation="Expand the README with more detail: what it does, why, and how to use it.",
                file="README.md",
                source="readme_analyzer",
            )
        )

    if readme_data.get("code_block_count", 0) == 0:
        issues.append(
            Issue(
                severity=Severity.MEDIUM,
                category=Category.DOCUMENTATION,
                title="No code examples in README",
                description="README has no fenced code blocks demonstrating usage.",
                recommendation="Add at least one runnable code example.",
                file="README.md",
                source="readme_analyzer",
            )
        )

    return issues


class DocsAnalyst(BaseAnalystAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__("DocsAnalyst", _SYSTEM_PROMPT, llm_client)

    def analyze(self, collector_results: Dict[str, Any]) -> Dict[str, Any]:
        readme_data = collector_results.get("readme", {})
        github_data = collector_results.get("github_metadata", {})

        issues = _readme_issues(readme_data)
        score = readme_data.get("quality_score", 0.0)

        readme_preview = (github_data.get("readme_content") or "")[:500]
        prompt = (
            f"README quality score: {score:.0f}/100\n"
            f"Word count: {readme_data.get('word_count', 0)}\n"
            f"Missing sections: {readme_data.get('missing_sections', [])}\n"
            f"Has table of contents: {readme_data.get('has_table_of_contents', False)}\n"
            f"README excerpt:\n{readme_preview}\n\n"
            "Summarize documentation quality and the single highest-impact fix."
        )
        summary = self._call_llm(prompt)

        return {
            "summary": summary,
            "score": score,
            "issues": [issue_to_dict(i) for i in issues],
        }
