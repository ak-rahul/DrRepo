"""Code-quality analyst: ruff findings plus complexity and duplication (any language),
normalized by code size."""

from __future__ import annotations

from typing import Any

from drrepo.agents.analysts.base import (
    Analyst,
    Assessment,
    Recon,
    aggregate,
    collector_data,
    collector_detail,
    decay_score,
    issue_penalty,
    sort_issues,
)
from drrepo.models import Category, Issue, Location, Severity

# Real bugs (undefined names, syntax errors, broken comparisons) vs. likely bugs
# (bugbear) vs. hygiene (unused imports/variables, style).
_HIGH_PREFIXES = ("E9", "F63", "F7", "F82", "PLE", "syntax-error")
_MEDIUM_PREFIXES = ("B", "F50", "F52", "F60")
# Penalty per 1k lines of Python that maps to ~37/100.
_PENALTY_PER_KLOC_SCALE = 30.0
_ABSOLUTE_SCALE = 80.0
# Complexity bands: above the collector's threshold (15) is hard to test,
# above this one is hard to change safely.
VERY_HIGH_CCN = 30
DUPLICATION_LOW = 0.05
DUPLICATION_MEDIUM = 0.15
MIN_DUPLICATED_LINES = 50
_SAMPLES = 5


def _penalty_score(issues: list[Issue], lines: int) -> float:
    """Penalty normalized per 1k lines when the size is known, so big codebases aren't punished for size."""
    penalty = issue_penalty(issues)
    if lines:
        return decay_score(penalty / max(lines / 1000.0, 1.0), _PENALTY_PER_KLOC_SCALE)
    return decay_score(penalty, _ABSOLUTE_SCALE)


def _size(recon: Recon) -> int:
    """Lines the penalty is normalized by: Python lines, else the measured code in any language."""
    layout = collector_data(recon, "repo_layout") or {}
    complexity = collector_data(recon, "complexity") or {}
    return int(layout.get("python_lines") or 0) or int(complexity.get("nloc") or 0)


def _function_list(functions: list[dict[str, Any]], metric: str) -> str:
    return "; ".join(
        f"{f['file']}:{f['line']} {f['name']} ({metric} {f[metric]})" for f in functions[:_SAMPLES]
    )


def complexity_issues(data: dict[str, Any]) -> list[Issue]:
    """Aggregated issues from the complexity collector: one per band, plus duplication."""
    thresholds = data.get("thresholds") or {}
    ccn_floor = int(thresholds.get("ccn", 15))
    nloc_floor = int(thresholds.get("nloc", 100))
    complex_functions: list[dict[str, Any]] = data.get("complex_functions") or []
    total_complex = int(data.get("complex_count", len(complex_functions)))
    very = [f for f in complex_functions if f["ccn"] > VERY_HIGH_CCN]
    # Samples are the worst 30, so a count beyond them can only be in the lower band.
    high = [f for f in complex_functions if f["ccn"] <= VERY_HIGH_CCN]
    high_count = total_complex - len(very)

    issues = []
    for functions, count, severity, rule, floor in (
        (very, len(very), Severity.MEDIUM, "very-high-complexity", VERY_HIGH_CCN),
        (high, high_count, Severity.LOW, "high-complexity", ccn_floor),
    ):
        if count <= 0:
            continue
        issues.append(
            Issue(
                severity=severity,
                category=Category.CODE_QUALITY,
                title=f"{count} function{'s' if count != 1 else ''} above cyclomatic complexity {floor}",
                description=(
                    f"Functions with many independent paths are hard to test and to change "
                    f"safely. Worst: {_function_list(functions, 'ccn')}."
                ),
                recommendation="Split these functions into smaller ones, starting with the most complex.",
                source="lizard",
                rule_id=rule,
                locations=[Location(f["file"], f["line"]) for f in functions[:_SAMPLES]],
                occurrences=count,
            )
        )

    long_functions: list[dict[str, Any]] = data.get("long_functions") or []
    long_count = int(data.get("long_count", len(long_functions)))
    if long_count:
        issues.append(
            Issue(
                severity=Severity.LOW,
                category=Category.CODE_QUALITY,
                title=f"{long_count} function{'s' if long_count != 1 else ''} longer than {nloc_floor} lines of code",
                description=f"Longest: {_function_list(long_functions, 'nloc')}.",
                recommendation="Extract the distinct steps of each long function into named helpers.",
                source="lizard",
                rule_id="long-function",
                locations=[Location(f["file"], f["line"]) for f in long_functions[:_SAMPLES]],
                occurrences=long_count,
            )
        )

    duplication = data.get("duplication") or {}
    ratio = duplication.get("ratio")
    duplicated = int(duplication.get("duplicated_lines") or 0)
    if (
        isinstance(ratio, (int, float))
        and ratio >= DUPLICATION_LOW
        and duplicated >= MIN_DUPLICATED_LINES
    ):
        blocks: list[dict[str, Any]] = duplication.get("blocks") or []
        examples = "; ".join(
            f"{b['file']}:{b['line']}-{b['end_line']} also at {b['also_in']['file']}:{b['also_in']['line']}"
            for b in blocks[:_SAMPLES]
        )
        issues.append(
            Issue(
                severity=Severity.MEDIUM if ratio >= DUPLICATION_MEDIUM else Severity.LOW,
                category=Category.CODE_QUALITY,
                title=f"{ratio:.0%} of code lines are duplicated ({duplicated:,} lines)",
                description=(
                    f"Copy-pasted blocks of {thresholds.get('window', 8)} or more code lines. "
                    f"Largest: {examples}."
                ),
                recommendation="Move each repeated block into one shared function or module.",
                source="duplication",
                rule_id="duplicated-code",
                locations=[Location(b["file"], b["line"]) for b in blocks[:_SAMPLES]],
            )
        )
    return issues


def ruff_severity(finding: dict[str, Any]) -> Severity:
    rule = str(finding.get("rule") or "")
    if rule.startswith(_HIGH_PREFIXES):
        return Severity.HIGH
    if rule.startswith(_MEDIUM_PREFIXES):
        return Severity.MEDIUM
    return Severity.LOW


def _title(finding: dict[str, Any], count: int) -> str:
    rule = finding.get("rule")
    message = (finding.get("message") or "").split("\n")[0][:80]
    return f"{rule}: {message}" if count == 1 else f"{rule} ({count} occurrences)"


def _recommendation(finding: dict[str, Any]) -> str:
    url = finding.get("url")
    return f"Fix the {finding.get('rule')} findings" + (f" (see {url})." if url else ".")


class CodeQualityAnalyst(Analyst):
    category = Category.CODE_QUALITY
    tool_families = ("files", "symbols", "scanners")
    recon_inputs = ("static_analysis", "complexity", "repo_layout")
    rescore_scale = 60.0

    def score_issues(self, recon: Recon, issues: list[Issue]) -> float | None:
        return _penalty_score(issues, _size(recon))

    def assess(self, recon: Recon) -> Assessment:
        static = collector_data(recon, "static_analysis")
        layout = collector_data(recon, "repo_layout") or {}
        complexity = collector_data(recon, "complexity") or {}
        python_lines = int(layout.get("python_lines") or 0)
        measured = int(complexity.get("functions") or 0) > 0

        if static is None and not measured:
            detail = collector_detail(recon, "static_analysis", "static analysis did not run")
            return self.unassessed(f"Code quality could not be assessed: {detail}.")
        if layout and python_lines == 0 and not measured:
            languages = (
                ", ".join(list(layout.get("lines_by_language", {}))[:3]) or "no recognized source"
            )
            return self.unassessed(
                f"Code quality not scored: linting covers Python, complexity metrics found no "
                f"functions, and this repository contains {languages}."
            )

        # ruff only covers Python; a repository without Python is scored on complexity alone.
        findings = (static or {}).get("findings", []) if python_lines or not layout else []
        lint_issues = aggregate(
            findings,
            category=self.category,
            severity_of=ruff_severity,
            title_of=_title,
            recommendation_of=_recommendation,
        )
        metric_issues = complexity_issues(complexity) if measured else []
        issues = sort_issues(lint_issues + metric_issues)
        score = _penalty_score(issues, _size(recon))

        parts = []
        if static is None:
            detail = collector_detail(recon, "static_analysis", "static analysis did not run")
            parts.append(f"ruff did not run ({detail}).")
        elif python_lines or not layout:
            size = f" across {python_lines:,} lines of Python" if python_lines else ""
            if findings:
                top = ", ".join(f"{i.rule_id} x{i.occurrences}" for i in lint_issues[:6])
                high = sum(i.occurrences for i in lint_issues if i.severity == Severity.HIGH)
                parts.append(
                    f"ruff reported {len(findings)} findings in {len(lint_issues)} rule groups"
                    f"{size}; {high} are likely bugs. Most frequent: {top}."
                )
            else:
                parts.append(f"ruff found no bug-class issues{size}.")
        if measured:
            duplication = complexity.get("duplication") or {}
            ratio = duplication.get("ratio")
            parts.append(
                f"{complexity['functions']:,} functions in {complexity.get('files_analyzed', 0):,} "
                f"files: average complexity {complexity.get('average_ccn')}, "
                f"{complexity.get('complex_count', 0)} above {(complexity.get('thresholds') or {}).get('ccn', 15)}"
                + (f", {ratio:.1%} duplicated lines" if isinstance(ratio, (int, float)) else "")
                + "."
            )
        summary = " ".join(parts)
        if not issues:
            return Assessment(issues=[], score=100.0, summary=summary)
        facts = f"{summary}\nTop issue groups:\n" + "\n".join(
            f"- [{i.severity.value}] {i.title} (e.g. {i.file}:{i.line})" for i in issues[:10]
        )
        return Assessment(issues=issues, score=score, summary=summary, narrative_facts=facts)
