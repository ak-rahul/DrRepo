"""Documentation analyst: README metrics and deterministic doc checks, plus a bounded
LLM rubric when available.

The score is the README quality metric, minus a bounded penalty (at most
`DOC_CHECK_MAX_PENALTY` points) for what `recon/doc_checks.py` found: broken
links and anchors, documented commands that don't exist, and low docstring
coverage of public Python APIs.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from drrepo.agents import rubric
from drrepo.agents.analysts.base import (
    Analyst,
    Assessment,
    Recon,
    collector_data,
    issue_penalty,
)
from drrepo.agents.llm import LLMRuntime
from drrepo.log import logger
from drrepo.models import Category, Issue, Location, Severity

_CRITICAL_SECTIONS = {"Installation", "Usage"}
DOC_CHECK_MAX_PENALTY = 15.0
MIN_PUBLIC_APIS_FOR_COVERAGE = 10
_MAX_LOCATIONS = 20


def doc_check_issues(checks: dict[str, Any] | None, readme_file: str) -> list[Issue]:
    """Issues from the `doc_checks` collector: one per file with broken links, one per
    missing command, and one for low docstring coverage."""
    if not checks:
        return []
    issues: list[Issue] = []
    by_file: dict[str, list[dict[str, Any]]] = {}
    for link in checks.get("broken_links", []):
        by_file.setdefault(link["file"], []).append(link)
    for file, links in by_file.items():
        shown = "; ".join(f"{link['target']} ({link['reason']})" for link in links[:5])
        more = f"; and {len(links) - 5} more" if len(links) > 5 else ""
        issues.append(
            Issue(
                severity=Severity.MEDIUM if file == readme_file else Severity.LOW,
                category=Category.DOCUMENTATION,
                title=f"{len(links)} broken link(s) in {file}",
                description=f"Links to files or anchors that don't exist: {shown}{more}.",
                recommendation="Fix or remove the links; anchors must match a heading's slug.",
                source="doc_checks",
                rule_id="broken-link",
                locations=[Location(file, link["line"]) for link in links[:_MAX_LOCATIONS]],
                occurrences=len(links),
            )
        )
    issues.extend(
        Issue(
            severity=Severity.MEDIUM,
            category=Category.DOCUMENTATION,
            title=f"Documented command doesn't exist: {command['command'][:80]}",
            description=f"The docs show `{command['command']}`, but {command['reason']}.",
            recommendation="Update the docs, or add the script, target or entry point they describe.",
            source="doc_checks",
            rule_id="missing-command",
            locations=[Location(command["file"], command["line"])],
        )
        for command in checks.get("missing_commands", [])
    )
    docstrings = checks.get("docstrings") or {}
    coverage, public = docstrings.get("coverage"), int(docstrings.get("public", 0))
    if coverage is not None and public >= MIN_PUBLIC_APIS_FOR_COVERAGE and coverage < 0.5:
        samples = docstrings.get("undocumented", [])
        issues.append(
            Issue(
                severity=Severity.MEDIUM if coverage < 0.2 else Severity.LOW,
                category=Category.DOCUMENTATION,
                title=f"Docstrings cover {coverage:.0%} of {public} public Python APIs",
                description=(
                    f"{public - int(docstrings.get('documented', 0))} public functions, classes "
                    "or methods in package code have no docstring, for example "
                    + ", ".join(f"{s['name']} ({s['file']}:{s['line']})" for s in samples[:5])
                    + "."
                ),
                recommendation="Document the public API, starting with the entry points users call first.",
                source="doc_checks",
                rule_id="docstring-coverage",
                locations=[Location(s["file"], s["line"]) for s in samples[:_MAX_LOCATIONS]],
            )
        )
    return issues


class DocumentationAnalyst(Analyst):
    category = Category.DOCUMENTATION
    tool_families = ("files",)
    rescore_scale = 60.0

    def score_issues(self, recon: Recon, issues: list[Issue]) -> float | None:
        return None  # the score is the README quality metric, not an issue penalty

    def assess(self, recon: Recon) -> Assessment:
        readme = collector_data(recon, "readme")
        if readme is None:
            return self.unassessed(
                "Documentation could not be assessed: the README could not be retrieved."
            )

        layout = collector_data(recon, "repo_layout") or {}
        structure = layout.get("file_structure", {})
        readme_file = layout.get("readme_path") or "README.md"
        words = readme.get("word_count", 0)
        issues: list[Issue] = []

        if words == 0:
            issues.append(
                Issue(
                    severity=Severity.HIGH,
                    category=self.category,
                    title="No README",
                    description="The repository has no README (or it is empty).",
                    recommendation="Add a README covering what the project does, how to install it, and how to use it.",
                    source="readme_analyzer",
                    rule_id="missing-readme",
                )
            )
        else:
            for section in readme.get("missing_sections", []):
                if section == "License" and structure.get("has_license"):
                    severity = (
                        Severity.LOW
                    )  # a LICENSE file exists; the README just doesn't mention it
                elif section in _CRITICAL_SECTIONS:
                    severity = Severity.HIGH
                else:
                    severity = (
                        Severity.LOW if section in ("Examples", "Features") else Severity.MEDIUM
                    )
                issues.append(
                    Issue(
                        severity=severity,
                        category=self.category,
                        title=f"README has no '{section}' section",
                        description=f"No README heading covers {section.lower()}.",
                        recommendation=f"Add a '{section}' section to the README.",
                        source="readme_analyzer",
                        rule_id=f"missing-section-{section.lower()}",
                        locations=[Location(file=readme_file)],
                    )
                )
            if words < 150:
                issues.append(
                    Issue(
                        severity=Severity.MEDIUM,
                        category=self.category,
                        title="README is very short",
                        description=f"The README has only {words} words of prose.",
                        recommendation="Explain what the project does, why, and how to get started.",
                        source="readme_analyzer",
                        rule_id="short-readme",
                        locations=[Location(file=readme_file)],
                    )
                )
            if readme.get("code_block_count", 0) == 0:
                issues.append(
                    Issue(
                        severity=Severity.MEDIUM,
                        category=self.category,
                        title="README has no code examples",
                        description="No fenced code blocks show how to install or use the project.",
                        recommendation="Add at least one copy-pasteable install and usage example.",
                        source="readme_analyzer",
                        rule_id="no-code-examples",
                        locations=[Location(file=readme_file)],
                    )
                )

        checks = collector_data(recon, "doc_checks")
        check_issues = doc_check_issues(checks, readme_file)
        issues += check_issues
        metric = float(readme.get("quality_score", 0.0))
        penalty = min(DOC_CHECK_MAX_PENALTY, issue_penalty(check_issues))
        score = round(max(0.0, metric - penalty), 1)
        # The clone's README is the pinned commit's; the API serves HEAD.
        excerpt = (
            layout.get("readme_content")
            or (collector_data(recon, "github_metadata") or {}).get("readme_content")
            or ""
        )[:800]
        facts = (
            f"README quality score: {score:.0f}/100; {words} words; "
            f"{readme.get('section_count', 0)} headings; {readme.get('code_block_count', 0)} code blocks.\n"
            f"Missing sections: {readme.get('missing_sections', [])}\n"
            f"Doc checks: {len((checks or {}).get('broken_links', []))} broken links, "
            f"{len((checks or {}).get('missing_commands', []))} documented commands that don't exist, "
            f"docstring coverage {((checks or {}).get('docstrings') or {}).get('coverage')}\n"
            f"Has docs/ directory: {structure.get('has_docs', 'unknown')}\n"
            f"README excerpt:\n{excerpt}"
        )
        summary = (
            f"README scores {metric:.0f}/100 ({words} words, {readme.get('section_count', 0)} sections)"
            + (f", minus {penalty:.0f} for documentation checks. " if penalty else ". ")
            + (
                f"Missing: {', '.join(readme.get('missing_sections', []))}."
                if readme.get("missing_sections")
                else "All essential sections are present."
            )
        )
        return Assessment(
            issues=issues, score=score, summary=summary, narrative_facts=facts if words else None
        )

    def judge(
        self,
        recon: Recon,
        assessment: Assessment,
        llm: LLMRuntime,
        clone_root: str | None,
    ) -> Assessment:
        """Grade the README against the rubric and move the score within ±MAX_ADJUSTMENT."""
        layout = collector_data(recon, "repo_layout") or {}
        readme = layout.get("readme_content") or (
            collector_data(recon, "github_metadata") or {}
        ).get("readme_content")
        if not assessment.assessed or not readme:
            return assessment
        try:
            result = rubric.evaluate(
                llm,
                readme,
                layout.get("build_config") or {},
                layout.get("file_structure") or {},
                clone_root,
            )
        except Exception as e:
            logger.warning(f"documentation rubric failed ({e}); using README metrics only")
            return dataclasses.replace(
                assessment,
                notes=[
                    *assessment.notes,
                    f"Documentation rubric unavailable ({type(e).__name__}); README metrics only.",
                ],
            )
        if result.rubric_score is None:
            return assessment

        readme_file = layout.get("readme_path") or "README.md"
        issues = [self._reconcile(issue, result) for issue in assessment.issues]
        covered = {i.rule_id for i in issues}
        for name, item in result.items.items():
            if item.verdict not in ("missing", "partial"):
                continue
            sections = rubric.SECTIONS_BY_CRITERION.get(name, ())
            if any(f"missing-section-{s.lower()}" in covered for s in sections):
                continue  # the metric already reports it
            severity = (
                Severity.MEDIUM
                if item.verdict == "missing" and name in ("installation", "usage")
                else Severity.LOW
            )
            issues.append(
                Issue(
                    severity=severity,
                    category=self.category,
                    title=f"README {'does not cover' if item.verdict == 'missing' else 'only partly covers'} {name}",
                    description=f"{item.reason} (Rubric criterion: the README {rubric.CRITERIA[name]}.)",
                    recommendation=f"Make sure the README {rubric.CRITERIA[name]}.",
                    source="doc_rubric",
                    rule_id=f"rubric-{name}",
                    locations=[Location(file=readme_file)],
                )
            )

        score = rubric.bounded_score(assessment.score, result.rubric_score)
        counts = ", ".join(f"{n} {v}" for v, n in result.counts().items() if n)
        note = (
            f"Documentation rubric ({counts}): score {assessment.score:.0f} -> {score:.0f} "
            f"(LLM judgment, bounded to ±{rubric.MAX_ADJUSTMENT:.0f})."
        )
        notes = [*assessment.notes, note]
        if result.spot_check_downgrades:
            notes.append(
                "Rubric verdicts citing missing files were downgraded: "
                + ", ".join(result.spot_check_downgrades)
                + "."
            )
        facts = (
            (assessment.narrative_facts or "")
            + "\nRubric verdicts:\n"
            + "\n".join(
                f"- {name}: {item.verdict} ({item.reason})" for name, item in result.items.items()
            )
        )
        return dataclasses.replace(
            assessment, issues=issues, score=score, notes=notes, narrative_facts=facts
        )

    @staticmethod
    def _reconcile(issue: Issue, result: rubric.RubricResult) -> Issue:
        """A heading-based "missing section" the rubric found covered is downgraded, not removed."""
        for name, sections in rubric.SECTIONS_BY_CRITERION.items():
            item = result.items.get(name)
            if (
                item is not None
                and item.verdict == "met"
                and issue.rule_id in {f"missing-section-{s.lower()}" for s in sections}
            ):
                return dataclasses.replace(
                    issue,
                    severity=Severity.LOW,
                    description=f"{issue.description} The documentation rubric found it covered "
                    f"under another heading: {item.reason}",
                )
        return issue
