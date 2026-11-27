"""Documentation analyst: README completeness and structure."""

from __future__ import annotations

from drrepo.agents.analysts.base import Analyst, Assessment, Recon, collector_data
from drrepo.models import Category, Issue, Location, Severity

_CRITICAL_SECTIONS = {"Installation", "Usage"}


class DocumentationAnalyst(Analyst):
    category = Category.DOCUMENTATION
    tool_families = ("files",)
    rescore_scale = 60.0

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

        score = float(readme.get("quality_score", 0.0))
        excerpt = (
            (collector_data(recon, "github_metadata") or {}).get("readme_content")
            or layout.get("readme_content")
            or ""
        )[:800]
        facts = (
            f"README quality score: {score:.0f}/100; {words} words; "
            f"{readme.get('section_count', 0)} headings; {readme.get('code_block_count', 0)} code blocks.\n"
            f"Missing sections: {readme.get('missing_sections', [])}\n"
            f"Has docs/ directory: {structure.get('has_docs', 'unknown')}\n"
            f"README excerpt:\n{excerpt}"
        )
        summary = (
            f"README scores {score:.0f}/100 ({words} words, {readme.get('section_count', 0)} sections). "
            + (
                f"Missing: {', '.join(readme.get('missing_sections', []))}."
                if readme.get("missing_sections")
                else "All essential sections are present."
            )
        )
        return Assessment(
            issues=issues, score=score, summary=summary, narrative_facts=facts if words else None
        )
