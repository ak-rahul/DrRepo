"""Compare two reports of one repository: what a change made better or worse.

Pure functions over `Report.to_dict()` output, so the comparison is unit-tested
offline and works on any two saved reports. `AnalysisService.compare()` produces
the two reports (base and head commits) and calls `diff_reports`.

Issue identity across commits ignores line numbers, which shift with any edit
above a finding: an issue is the same when its category, source, rule (or, for
checks without a stable rule id, its title) and file match. README findings
ignore the file too, because they describe whichever README the commit has
(renaming README.rst to README.md fixes nothing). Grounding and critic marks are
stripped first, so a re-verified agent finding is not "new".

The diff document has its own contract, `diff.schema.json` (draft 2020-12),
validated in tests like the report schema.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib.resources import files
from typing import Any

from drrepo.models import REPORT_SCHEMA_VERSION, Severity
from drrepo.report.schema import load_schema

DIFF_SCHEMA_VERSION = "1.0"
# Rule ids that name a kind of finding rather than one check; the title identifies those.
_GENERIC_RULE_IDS = {None, "", "agent-finding"}
_MARKS = re.compile(r"^(?:\[(?:unverified|disputed)\]\s*)+")
_COUNT_SUFFIX = re.compile(r"\s*\(\d+ occurrences?\)$")
# Sources whose findings are about the repository's README, not one file's content.
_README_SOURCES = {"readme_analyzer", "doc_rubric"}


def issue_identity(issue: dict[str, Any]) -> str:
    """Stable identity of a finding across commits (no line number)."""
    rule = issue.get("rule_id")
    if rule in _GENERIC_RULE_IDS:
        rule = _COUNT_SUFFIX.sub("", _MARKS.sub("", issue["title"])).strip().lower()
    where = "" if issue["source"] in _README_SOURCES else issue.get("file") or ""
    return f"{issue['category']}|{issue['source']}|{rule}|{where}"


def _side(report: dict[str, Any]) -> dict[str, Any]:
    repo = report.get("repository", {})
    return {
        "ref": repo.get("ref"),
        "commit_sha": repo.get("commit_sha"),
        "overall_score": report.get("overall_score"),
    }


def _score(cs: dict[str, Any] | None) -> float | None:
    if not cs or not cs.get("assessed", True):
        return None
    return float(cs["score"])


def diff_reports(base: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    """New, fixed and worsened issues, plus score deltas, from `base` to `head`."""
    base_issues = {issue_identity(i): i for i in base.get("issues", [])}
    head_issues = {issue_identity(i): i for i in head.get("issues", [])}
    new = [i for key, i in head_issues.items() if key not in base_issues]
    fixed = [i for key, i in base_issues.items() if key not in head_issues]
    worsened = []
    for key, now in head_issues.items():
        before = base_issues.get(key)
        if before is None:
            continue
        severity_rose = Severity(now["severity"]).rank < Severity(before["severity"]).rank
        if severity_rose or now.get("occurrences", 1) > before.get("occurrences", 1):
            worsened.append(
                {
                    "issue": now,
                    "base_severity": before["severity"],
                    "base_occurrences": before.get("occurrences", 1),
                }
            )

    names = list(head.get("category_scores", {})) + [
        n for n in base.get("category_scores", {}) if n not in head.get("category_scores", {})
    ]
    categories = {}
    for name in names:
        was = _score(base.get("category_scores", {}).get(name))
        now = _score(head.get("category_scores", {}).get(name))
        delta = round(now - was, 1) if was is not None and now is not None else None
        categories[name] = {"base": was, "head": now, "delta": delta}

    base_overall, head_overall = base.get("overall_score"), head.get("overall_score")
    return {
        "diff_schema_version": DIFF_SCHEMA_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "repository": {k: head.get("repository", {}).get(k) for k in ("name", "full_name", "url")},
        "base": _side(base),
        "head": _side(head),
        "overall_delta": round(head_overall - base_overall, 1)
        if base_overall is not None and head_overall is not None
        else None,
        "category_deltas": categories,
        "new_issues": _by_severity(new),
        "fixed_issues": _by_severity(fixed),
        "worsened_issues": sorted(worsened, key=lambda w: Severity(w["issue"]["severity"]).rank),
        "unchanged_issues": len(head_issues) - len(new) - len(worsened),
        "deep_categories": [],
        "generated_at": head.get("generated_at", ""),
        "drrepo_version": head.get("drrepo_version", ""),
    }


def _by_severity(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=lambda i: Severity(i["severity"]).rank)


def worsened_categories(diff: dict[str, Any]) -> list[str]:
    """Categories whose score fell, or that gained a new or worsened issue."""
    changed = {i["category"] for i in diff["new_issues"]} | {
        w["issue"]["category"] for w in diff["worsened_issues"]
    }
    fell = {n for n, c in diff["category_deltas"].items() if (c["delta"] or 0) < 0}
    return sorted(changed | fell)


def gate(
    diff: dict[str, Any], fail_on_new: str | None = None, max_score_drop: float | None = None
) -> list[str]:
    """Reasons the change should fail a CI gate (empty means pass)."""
    reasons = []
    if fail_on_new:
        floor = Severity(fail_on_new).rank
        blocking = [i for i in diff["new_issues"] if Severity(i["severity"]).rank <= floor]
        blocking += [
            w["issue"]
            for w in diff["worsened_issues"]
            if Severity(w["issue"]["severity"]).rank <= floor
        ]
        if blocking:
            reasons.append(
                f"{len(blocking)} new or worsened issue(s) at {fail_on_new} severity or above"
            )
    delta = diff.get("overall_delta")
    if max_score_drop is not None and delta is not None and -delta > max_score_drop:
        reasons.append(f"overall score fell {delta:+.1f} (allowed: -{max_score_drop:g})")
    return reasons


_SHARED_DEFS = ("score", "category", "severity", "location", "issue")


@cache
def load_diff_schema() -> dict[str, Any]:
    """The diff schema, with the shared definitions merged in from the report schema
    (one source of truth for what an issue is)."""
    resource = files("drrepo.report") / "diff.schema.json"
    schema: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    report_defs = load_schema()["$defs"]
    schema["$defs"].update({name: report_defs[name] for name in _SHARED_DEFS})
    return schema


def validate_diff(diff: dict[str, Any]) -> None:
    """Raise `jsonschema.ValidationError` if `diff` breaks the diff contract.

    Needs `jsonschema` (a development dependency), like `report.schema.validate`.
    """
    import jsonschema

    jsonschema.validate(diff, load_diff_schema(), cls=jsonschema.Draft202012Validator)
