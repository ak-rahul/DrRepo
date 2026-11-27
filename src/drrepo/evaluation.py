"""`drrepo eval`: measure whether a change made reports better or worse.

Runs a fixed set of public repositories, each pinned to an exact commit
(`evals/repos.toml`), and compares the results with a recorded baseline
(`evals/baseline.json`). Everything here except `run_cases` is pure, so the
comparison logic is unit-tested offline.

Why compare against a baseline with a tolerance, not exact equality: even at a
pinned commit, two inputs are live. OSV advisories (the dependencies score)
and GitHub metadata such as last-push age (maintainability) change over time.
A drift beyond the tolerance, or a finding that appears or disappears, is what
a reviewer needs to look at.

Precision of agent findings is computed from human labels in
`evals/labels.toml`; unlabeled findings are counted, never guessed.
"""

from __future__ import annotations

import json
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drrepo.agents.grounding import UNVERIFIED_MARK
from drrepo.log import logger
from drrepo.models import Category

AGENT_SOURCE_PREFIX = "investigator:"
DEFAULT_TOLERANCE = 5.0


@dataclass(frozen=True)
class EvalCase:
    name: str
    url: str
    ref: str
    notes: str = ""


def load_cases(path: Path) -> list[EvalCase]:
    """Parse `[[case]]` tables. Raises ValueError for a malformed manifest."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = []
    for raw in data.get("case", []):
        missing = {"name", "url", "ref"} - raw.keys()
        if missing:
            raise ValueError(f"{path}: case {raw.get('name', '?')!r} is missing {sorted(missing)}")
        if len(raw["ref"]) != 40:
            raise ValueError(f"{path}: case {raw['name']!r} must pin a full 40-character SHA")
        cases.append(EvalCase(raw["name"], raw["url"], raw["ref"], raw.get("notes", "")))
    names = [c.name for c in cases]
    if len(names) != len(set(names)):
        raise ValueError(f"{path}: case names must be unique")
    return cases


def load_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    labels = tomllib.loads(path.read_text(encoding="utf-8")).get("labels", {})
    bad = {k: v for k, v in labels.items() if v not in ("true_positive", "false_positive")}
    if bad:
        raise ValueError(f"{path}: labels must be true_positive or false_positive: {bad}")
    return dict(labels)


def finding_key(case: str, issue: dict[str, Any]) -> str:
    """Stable identity for a finding across runs (independent of wording changes)."""
    title = issue["title"].removeprefix(f"{UNVERIFIED_MARK} ")
    what = issue.get("rule_id") or title
    return f"{case}|{issue['category']}|{issue['source']}|{what}|{issue.get('file') or ''}"


def summarize(case: EvalCase, report: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    """The comparable essentials of one report."""
    issues = report.get("issues", [])
    agent = [i for i in issues if i["source"].startswith(AGENT_SOURCE_PREFIX)]
    categories = report.get("category_scores", {})
    return {
        "case": case.name,
        "commit_sha": report.get("repository", {}).get("commit_sha"),
        "overall": report.get("overall_score"),
        "categories": {
            name: (cs["score"] if cs.get("assessed", True) else None)
            for name, cs in categories.items()
        },
        "findings": sorted({finding_key(case.name, i) for i in issues}),
        "agent_findings": sorted({finding_key(case.name, i) for i in agent}),
        "unverified_agent_findings": sum(i["title"].startswith(UNVERIFIED_MARK) for i in agent),
        "deep_categories": sorted(
            n for n, cs in categories.items() if cs.get("investigation_depth") == "deep"
        ),
        "tool_calls": sum(len(cs.get("investigation_trace", [])) for cs in categories.values()),
        "tokens": (report.get("llm_usage") or {}).get("used_tokens"),
        "elapsed_seconds": round(elapsed_seconds, 1),
    }


def run_cases(
    analyze: Callable[[EvalCase], dict[str, Any]],
    cases: list[EvalCase],
    progress: Callable[[str], None] = lambda _m: None,
) -> dict[str, dict[str, Any]]:
    """Run every case; a case that fails is recorded with its error, never aborts the set."""
    results: dict[str, dict[str, Any]] = {}
    for case in cases:
        progress(f"eval: {case.name} @ {case.ref[:12]}")
        started = time.monotonic()
        try:
            report = analyze(case)
        except Exception as e:
            logger.exception(f"eval case {case.name} failed")
            results[case.name] = {"case": case.name, "error": f"{type(e).__name__}: {e}"}
            continue
        results[case.name] = summarize(case, report, time.monotonic() - started)
    return results


@dataclass
class CaseDiff:
    case: str
    error: str | None = None
    overall_delta: float | None = None
    category_deltas: dict[str, float | None] = field(default_factory=dict)
    new_findings: list[str] = field(default_factory=list)
    gone_findings: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    cases: list[CaseDiff]
    agent_precision: float | None
    labeled_agent_findings: int
    unlabeled_agent_findings: int

    @property
    def regressed(self) -> bool:
        return any(c.regressions or c.error for c in self.cases)


def _delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 1)


def compare(
    current: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    labels: dict[str, str] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Comparison:
    """Diff `current` against `baseline`. A score drop beyond `tolerance`, a category
    becoming unassessable, or a failed case counts as a regression."""
    labels = labels or {}
    diffs: list[CaseDiff] = []
    for name, result in current.items():
        diff = CaseDiff(case=name, error=result.get("error"))
        base = baseline.get(name)
        if diff.error or base is None:
            if base is None and not diff.error:
                diff.regressions.append("no baseline for this case (run with --update-baseline)")
            diffs.append(diff)
            continue
        diff.overall_delta = _delta(result["overall"], base.get("overall"))
        if diff.overall_delta is not None and diff.overall_delta < -tolerance:
            diff.regressions.append(f"overall score fell {diff.overall_delta:+.1f}")
        for category in Category:
            now = result["categories"].get(category.value)
            before = base.get("categories", {}).get(category.value)
            diff.category_deltas[category.value] = _delta(now, before)
            if now is None and before is not None:
                diff.regressions.append(f"{category.value} is no longer assessed")
            elif (d := diff.category_deltas[category.value]) is not None and d < -tolerance:
                diff.regressions.append(f"{category.value} fell {d:+.1f}")
        before_findings = set(base.get("findings", []))
        now_findings = set(result["findings"])
        diff.new_findings = sorted(now_findings - before_findings)
        diff.gone_findings = sorted(before_findings - now_findings)
        diffs.append(diff)

    agent = [k for r in current.values() for k in r.get("agent_findings", [])]
    labeled = [labels[k] for k in agent if k in labels]
    precision = round(labeled.count("true_positive") / len(labeled), 3) if labeled else None
    return Comparison(
        cases=diffs,
        agent_precision=precision,
        labeled_agent_findings=len(labeled),
        unlabeled_agent_findings=len(agent) - len(labeled),
    )


def render_markdown(
    comparison: Comparison, current: dict[str, dict[str, Any]], tolerance: float
) -> str:
    """A table a reviewer can paste into a pull request."""
    names = [c.value for c in Category]
    header = ["case", "overall", *names, "findings +/-", "deep", "tool calls", "tokens", "time"]
    lines = [
        f"## DrRepo eval ({'REGRESSED' if comparison.regressed else 'ok'}, tolerance ±{tolerance:g})",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]

    def cell(value: float | None, delta: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{value:.0f}" + (f" ({delta:+.1f})" if delta else "")

    for diff in comparison.cases:
        result = current.get(diff.case, {})
        if diff.error:
            lines.append(f"| {diff.case} | **error**: {diff.error} |" + " |" * (len(header) - 2))
            continue
        row = [
            diff.case,
            cell(result.get("overall"), diff.overall_delta),
            *(cell(result["categories"].get(n), diff.category_deltas.get(n)) for n in names),
            f"+{len(diff.new_findings)} / -{len(diff.gone_findings)}",
            ", ".join(result.get("deep_categories", [])) or "-",
            str(result.get("tool_calls", 0)),
            str(result.get("tokens") if result.get("tokens") is not None else "-"),
            f"{result.get('elapsed_seconds', 0):.0f}s",
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    if comparison.agent_precision is not None:
        lines.append(
            f"Agent precision: **{comparison.agent_precision:.0%}** over "
            f"{comparison.labeled_agent_findings} labeled finding(s)"
            f" ({comparison.unlabeled_agent_findings} unlabeled)."
        )
    elif comparison.unlabeled_agent_findings:
        lines.append(
            f"{comparison.unlabeled_agent_findings} agent finding(s), none labeled yet: "
            "add verdicts to evals/labels.toml to measure precision."
        )
    for diff in comparison.cases:
        details = [f"- regression: {r}" for r in diff.regressions]
        details += [f"- new: `{k}`" for k in diff.new_findings]
        details += [f"- gone: `{k}`" for k in diff.gone_findings]
        if details:
            lines += ["", f"### {diff.case}", *details]
    return "\n".join(lines) + "\n"


def write_baseline(path: Path, results: dict[str, dict[str, Any]]) -> None:
    failed = [name for name, r in results.items() if r.get("error")]
    if failed:
        raise ValueError(f"not writing a baseline with failed cases: {failed}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # LF on every OS: the baseline is committed, so its diffs must not churn on line endings.
    text = json.dumps(results, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def read_baseline(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}
