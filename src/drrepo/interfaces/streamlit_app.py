"""DrRepo Streamlit UI. Launch with `drrepo ui`.

An analysis takes minutes, so it runs on a background thread that writes into a
plain `AnalysisJob` object (not `st.session_state`, which needs a script-run
context the worker thread doesn't have). A fragment re-renders every second to
show live progress and triggers a full rerun when the job finishes.

`AnalysisService` is cached with `st.cache_resource`, i.e. one per Streamlit
*process*: the LLM circuit breaker and dependency cache carry across sessions
and runs, while every run still gets a fresh token budget. The service also
keeps the latest reports, so "Recent analyses" survives a page refresh.

Text that came from the analyzed repository is untrusted and always passes
through `ui_data.escape_markdown` before a Markdown-rendering widget; tables
and code blocks show it as plain text.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from drrepo import __version__
from drrepo.config import Config
from drrepo.interfaces import ui_data as ui
from drrepo.interfaces.health import check_all
from drrepo.log import configure_logging, logger
from drrepo.models import RepoRef
from drrepo.recon.clone import validate_ref
from drrepo.report.exporters import (
    diff_to_markdown,
    to_cyclonedx,
    to_json,
    to_markdown,
    to_sarif,
    to_summary,
)
from drrepo.report.history import repo_key
from drrepo.report.suppressions import REPOSITORY_FILE, SuppressionError, append_suppression
from drrepo.report.synthesis import grade
from drrepo.service import AnalysisService

ISSUES_PER_PAGE = 50
MODES = ("Audit a commit", "Compare two commits")


@dataclass
class AnalysisJob:
    repo_url: str
    kind: str = "audit"  # audit | compare
    started_at: float = field(default_factory=time.time)
    messages: list[str] = field(default_factory=list)
    status: str = "running"  # running | done | error
    result: dict[str, Any] | None = None
    error: str | None = None


@st.cache_resource
def get_service() -> AnalysisService:
    config = Config.from_env()
    configure_logging(config.log_level, fmt=config.log_format)
    return AnalysisService(config)


def _run_job(job: AnalysisJob, work: Callable[[Callable[[str], None]], dict[str, Any]]) -> None:
    def run() -> None:
        try:
            job.result = work(job.messages.append)
            job.status = "done"
        except Exception as e:
            logger.exception(f"Analysis of {job.repo_url} failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"

    threading.Thread(target=run, daemon=True, name="drrepo-analysis").start()


def start_job(
    service: AnalysisService, repo_url: str, description: str, deep: bool, ref: str | None = None
) -> AnalysisJob:
    job = AnalysisJob(repo_url=repo_url)
    _run_job(
        job,
        lambda progress: service.analyze(
            repo_url, description, deep=deep, progress=progress, ref=ref
        ),
    )
    return job


def start_compare_job(
    service: AnalysisService,
    repo_url: str,
    base: str,
    head: str | None,
    description: str,
    deep: bool,
) -> AnalysisJob:
    job = AnalysisJob(repo_url=repo_url, kind="compare")
    _run_job(
        job,
        lambda progress: service.compare(
            repo_url, base, head, description, deep=deep, progress=progress
        ),
    )
    return job


# ---------------------------------------------------------------- sidebar ---


def _open_recent() -> None:
    st.session_state["view"] = st.session_state.get("recent")


def render_sidebar(service: AnalysisService) -> bool:
    config = service.config
    with st.sidebar:
        st.markdown("### DrRepo")
        st.caption(f"v{__version__} · {config.model_provider} · `{config.model_for()}`")
        deep = st.toggle(
            "Tool-calling investigations",
            value=config.enable_deep_investigation,
            help=(
                "Let the Lead Investigator send risky categories to a tool-calling agent "
                "(deep, or lite for borderline ones). In compare mode, only categories that "
                "got worse are investigated. Off = fast, deterministic pass."
            ),
        )

        recent = service.list_reports()
        if recent:
            st.markdown("---")
            st.selectbox(
                "Recent analyses",
                [r["repository"] for r in recent],
                index=None,
                placeholder="Open a report from this server",
                key="recent",
                on_change=_open_recent,
            )

        st.markdown("---")
        st.markdown(
            "**What it checks**\n\n"
            "- Security: bandit, semgrep, secret scan, CI workflows (zizmor), "
            "Dockerfiles (hadolint), OpenSSF Scorecard\n"
            "- Code quality: ruff\n"
            "- Dependencies: OSV.dev advisories, licenses and policy, SBOM\n"
            "- Documentation: README, links and anchors, documented commands, docstrings\n"
            "- Maintainability: tests, CI, policies, activity"
        )
        st.caption("Public repositories only. Code is parsed, never executed.")
        st.markdown("---")
        if st.button("Check connectivity", width="stretch"):
            with st.spinner("Checking LLM provider, GitHub, OSV.dev..."):
                st.session_state["health"] = check_all(config)
        health = st.session_state.get("health")
        if health:
            st.write(
                {"healthy": "✅ Healthy", "degraded": "⚠️ Degraded"}.get(
                    health["status"], "❌ Unhealthy"
                )
            )
            for name, c in health["components"].items():
                detail = f" — {ui.escape_markdown(c['detail'])}" if c.get("detail") else ""
                st.caption(f"{name}: {c['status']}{detail}")
        breaker = service.breaker_state()
        if breaker and breaker["state"] != "closed":
            st.warning(f"LLM circuit breaker is {breaker['state']}: LLM calls are being skipped.")
    return deep


@st.fragment(run_every=1)
def render_progress() -> None:
    job: AnalysisJob | None = st.session_state.get("job")
    if job is None:
        return
    if job.status != "running":
        # The job finished between fragment runs: one full-app rerun renders the result.
        if not st.session_state.get("job_shown"):
            st.session_state["job_shown"] = True
            st.rerun()
        return
    elapsed = int(time.time() - job.started_at)
    verb = "Comparing" if getattr(job, "kind", "audit") == "compare" else "Analyzing"
    with st.status(f"{verb} {job.repo_url} — {elapsed}s", expanded=True):
        for message in job.messages[-12:]:
            st.write(ui.escape_markdown(message))


# ----------------------------------------------------------------- report ---


def render_issue(
    issue: dict[str, Any],
    report: dict[str, Any] | None = None,
    suppress_to: Path | None = None,
    key: str = "",
) -> None:
    """One issue. With `report`, an agent finding shows what the agent read; with
    `suppress_to`, a form marks the issue as a false positive in that file."""
    with st.expander(ui.issue_heading(issue)):
        st.markdown(ui.escape_markdown(issue.get("description", "")))
        st.markdown(f"**Fix:** {ui.escape_markdown(issue.get('recommendation', ''))}")
        st.caption(
            ui.escape_markdown(
                f"{issue['category']} · source: {issue.get('source')} · "
                f"rule: {issue.get('rule_id') or '—'}"
            )
        )
        extra = issue.get("locations", [])[1:]
        if extra:
            also = ", ".join(f"{loc['file']}:{loc.get('line')}" for loc in extra[:10])
            st.caption("Also at: " + ui.escape_markdown(also))
        steps = ui.evidence_steps(issue, report) if report else []
        if steps:
            st.markdown("**What the agent read before reporting this**")
            for step in steps[:3]:
                st.caption(
                    ui.escape_markdown(f"{step['tool']} {json.dumps(step['tool_input'])[:200]}")
                )
                st.code(step["observation"], language="text")
        if suppress_to is not None:
            render_suppress_form(issue, suppress_to, key)


def render_suppress_form(issue: dict[str, Any], path: Path, key: str) -> None:
    with st.form(f"{key}-suppress", clear_on_submit=True, border=False):
        st.caption(f"Mark as a false positive: adds a suppression to `{path}`")
        c1, c2 = st.columns([3, 1])
        reason = c1.text_input(
            "Reason", placeholder="why this finding doesn't apply", key=f"{key}-reason"
        )
        expires = c2.date_input(
            "Expires", value=datetime.now(UTC).date() + timedelta(days=90), key=f"{key}-expires"
        )
        if st.form_submit_button("Add suppression"):
            try:
                append_suppression(path, issue, reason=reason, expires=expires)
            except (SuppressionError, OSError) as e:
                st.error(f"Not added: {e}")
            else:
                st.success(f"Added to {path}. It applies from the next analysis.")


def render_issues_tab(result: dict[str, Any], key: str, suppress_to: Path | None = None) -> None:
    issues = result.get("issues", [])
    categories = list(result.get("category_scores", {}))
    sources = sorted({i.get("source", "") for i in issues})
    c1, c2, c3 = st.columns(3)
    severities = c1.multiselect(
        "Severity", list(ui.SEVERITIES), default=list(ui.SEVERITIES), key=f"{key}-sev"
    )
    cats = c2.multiselect("Category", categories, default=categories, key=f"{key}-cat")
    chosen_sources = c3.multiselect("Source", sources, default=sources, key=f"{key}-src")
    c4, c5, c6 = st.columns([2, 1, 1])
    query = c4.text_input(
        "Search", placeholder="title, file, rule", key=f"{key}-q", label_visibility="collapsed"
    )
    origin = c5.selectbox("Origin", ui.ORIGINS, key=f"{key}-origin", label_visibility="collapsed")
    hide_marked = c6.toggle(
        "Hide unverified/disputed",
        key=f"{key}-marked",
        help="Agent findings the grounding check couldn't verify, or the critic disputed.",
    )
    shown = ui.filter_issues(
        issues,
        severities=severities,
        categories=cats,
        sources=chosen_sources,
        origin=origin,
        query=query,
        hide_marked=hide_marked,
    )
    if not shown:
        st.success("No matching issues.")
        return
    pages = max(1, -(-len(shown) // ISSUES_PER_PAGE))
    number = 1
    if pages > 1:
        number = int(
            st.number_input(
                f"Page (of {pages})", min_value=1, max_value=pages, value=1, key=f"{key}-page"
            )
        )
    visible, pages = ui.page(shown, number, ISSUES_PER_PAGE)
    st.caption(f"{len(shown)} matching issue(s) of {len(issues)}; page {number} of {pages}")
    for index, issue in enumerate(visible):
        render_issue(issue, result, suppress_to, key=f"{key}-issue-{number}-{index}")


def render_dependencies_tab(result: dict[str, Any], key: str) -> None:
    dependencies = result.get("dependencies", [])
    if not dependencies:
        st.info("No exactly versioned dependencies were found in manifests or lockfiles.")
        return
    runtime = sum(1 for d in dependencies if d["scope"] == "runtime")
    vulnerable = sum(1 for d in dependencies if d.get("vulnerabilities"))
    c1, c2, c3 = st.columns(3)
    c1.metric("Packages", len(dependencies))
    c2.metric("Runtime", runtime, help="The rest are development-only.")
    c3.metric("With advisories", vulnerable)
    only = st.toggle("Only packages with advisories", key=f"{key}-vuln")
    st.dataframe(ui.dependency_rows(result, vulnerable_only=only), hide_index=True, width="stretch")
    licenses = ui.license_counts(result)
    if licenses:
        st.markdown("#### Runtime licenses")
        st.dataframe(
            [{"license": k, "packages": v} for k, v in licenses.items()],
            hide_index=True,
            width="stretch",
        )


def render_investigation_tab(result: dict[str, Any]) -> None:
    plan = result.get("investigation_plan", {})
    if plan:
        st.markdown("#### Lead Investigator's plan")
        st.dataframe(
            [
                {"category": ui.label(n), "depth": p.get("depth"), "rationale": p.get("rationale")}
                for n, p in plan.items()
            ],
            hide_index=True,
            width="stretch",
        )
    for name, cs in result.get("category_scores", {}).items():
        trace = cs.get("investigation_trace", [])
        if not trace:
            continue
        depth = cs.get("investigation_depth", "deep")
        with st.expander(f"{ui.label(name)} — {depth}, {len(trace)} tool calls"):
            for call in trace:
                st.markdown(f"**{ui.escape_markdown(call['tool'])}**")
                st.code(json.dumps(call["tool_input"])[:500], language="json")
                st.code(call["observation"], language="text")
    usage = result.get("llm_usage")
    if usage:
        estimate = usage.get("deep_estimate") or {}
        st.markdown("#### LLM usage")
        st.caption(
            f"LLM usage this run: {usage.get('used_tokens', 0):,} of "
            f"{usage.get('max_tokens', 0):,} tokens"
            + (
                f"; a deep investigation was budgeted at {estimate['tokens']:,} tokens "
                f"({'measured from past runs' if estimate.get('source') == 'history' else 'configured estimate'})"
                if estimate
                else ""
            )
        )
        rows = ui.usage_rows(result)
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")


def render_details_tab(result: dict[str, Any]) -> None:
    tables = ui.provenance_rows(result)
    if tables["models"]:
        st.markdown("#### Models")
        st.dataframe(tables["models"], hide_index=True, width="stretch")
    if tables["tools"]:
        st.markdown("#### Scanner versions")
        st.dataframe(tables["tools"], hide_index=True, width="stretch")
    st.markdown("#### Collector status")
    st.dataframe(
        [{"collector": n, **s} for n, s in result.get("collector_status", {}).items()],
        hide_index=True,
        width="stretch",
    )
    if tables["instructions"]:
        with st.expander("Agent instruction hashes"):
            st.dataframe(tables["instructions"], hide_index=True, width="stretch")
    with st.expander("Raw report JSON"):
        st.json(result, expanded=False)


def render_trend(service: AnalysisService, repo: dict[str, Any]) -> None:
    try:
        runs = service.store.runs(repo_key(repo))
    except (OSError, sqlite3.Error):  # history is a convenience; the report still renders
        runs = []
    points = ui.history_points(runs)
    if len(points) >= 2:
        st.markdown("#### Score over time")
        st.line_chart(points, x="run", y="overall", height=200)


def render_downloads(result: dict[str, Any], key: str) -> None:
    repo = result.get("repository", {})
    slug = (repo.get("full_name") or repo.get("name") or "report").replace("/", "__")
    files = [
        ("JSON", to_json, "json", "application/json"),
        ("Markdown", to_markdown, "md", "text/markdown"),
        ("SARIF", to_sarif, "sarif", "application/sarif+json"),
        ("SBOM", to_cyclonedx, "cdx.json", "application/vnd.cyclonedx+json"),
        ("Summary", to_summary, "summary.md", "text/markdown"),
    ]
    for col, (name, export, ext, mime) in zip(st.columns(len(files)), files, strict=True):
        col.download_button(
            name,
            export(result),
            f"drrepo_{slug}.{ext}",
            mime,
            width="stretch",
            key=f"{key}-dl-{ext}",
        )


def render_report(
    result: dict[str, Any], service: AnalysisService | None = None, key: str = "report"
) -> None:
    repo = result.get("repository", {})
    score = float(result.get("overall_score", 0))
    history = result.get("score_history")

    st.markdown(f"## {ui.escape_markdown(repo.get('full_name') or repo.get('name'))}")
    if repo.get("description"):
        st.caption(ui.escape_markdown(repo["description"]))
    if repo.get("commit_sha"):
        at = f" on {ui.escape_markdown(repo['ref'])}" if repo.get("ref") else ""
        st.caption(f"Commit `{repo['commit_sha'][:12]}`{at}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Overall score",
        f"{score:.0f}/100 ({grade(score)})",
        delta=f"{history['overall_score_delta']:+.1f}" if history else None,
    )
    c2.metric("Stars", f"{repo.get('stars', 0):,}")
    c3.metric("Language", repo.get("language") or "—")
    counts = result.get("issue_counts", {})
    c4.metric("Issues", sum(counts.values()), help=", ".join(f"{n} {s}" for s, n in counts.items()))
    if history:
        st.caption(f"Delta vs. previous analysis on {history['previous_timestamp'][:10]}")

    categories = result.get("category_scores", {})
    cols = st.columns(max(len(categories), 1))
    deltas = (history or {}).get("category_score_deltas", {})
    for col, (name, cs) in zip(cols, categories.items(), strict=False):
        icon = ui.DEPTH_ICON.get(cs.get("investigation_depth", "shallow"), "")
        title = f"{icon} {ui.label(name)}" if icon else ui.label(name)
        if cs.get("assessed", True):
            col.metric(
                title,
                f"{cs['score']:.0f}",
                delta=f"{deltas[name]:+.1f}" if name in deltas else None,
                help=f"Investigation: {cs.get('investigation_depth', 'shallow')}",
            )
        else:
            col.metric(
                title,
                "n/a",
                help="Not assessable for this repository; excluded from the overall score.",
            )
    if service is not None:
        render_trend(service, repo)

    suppressed = result.get("suppressed", [])
    names = ["Summary", "Issues", "Dependencies", "How it investigated", "Details"]
    if suppressed:
        names.insert(2, f"Suppressed ({len(suppressed)})")
    tabs = dict(zip(names, st.tabs(names), strict=True))

    with tabs["Summary"]:
        for name, cs in categories.items():
            st.markdown(f"**{ui.label(name)}** · {cs.get('investigation_depth', 'shallow')}")
            st.markdown(ui.escape_markdown(cs.get("summary", "")))
            for note in cs.get("notes", []):
                st.caption(f"ℹ️ {ui.escape_markdown(note)}")
        if result.get("quick_wins"):
            st.markdown("#### Quick wins")
            for win in result["quick_wins"]:
                st.markdown(f"- {ui.escape_markdown(win)}")

    with tabs["Issues"]:
        render_issues_tab(
            result,
            key,
            suppress_to=Path(service.config.suppressions_file or REPOSITORY_FILE)
            if service is not None
            else None,
        )
    if suppressed:
        with tabs[f"Suppressed ({len(suppressed)})"]:
            st.caption("Excluded from scores and quick wins by a suppression file.")
            st.dataframe(ui.suppressed_rows(result), hide_index=True, width="stretch")
    with tabs["Dependencies"]:
        render_dependencies_tab(result, key)
    with tabs["How it investigated"]:
        render_investigation_tab(result)
    with tabs["Details"]:
        render_details_tab(result)

    render_downloads(result, key)


# ------------------------------------------------------------------- diff ---


def render_diff(diff: dict[str, Any], service: AnalysisService) -> None:
    repo, base, head = diff["repository"], diff["base"], diff["head"]
    st.markdown(f"## {ui.escape_markdown(repo.get('full_name'))}: what changed")

    def side(s: dict[str, Any]) -> str:
        sha = (s.get("commit_sha") or "?")[:12]
        ref = f" ({ui.escape_markdown(s['ref'])})" if s.get("ref") else ""
        return f"`{sha}`{ref}"

    st.caption(f"{side(base)} → {side(head)}")
    delta = diff.get("overall_delta")
    c1, c2, c3, c4 = st.columns(4)
    head_score = head.get("overall_score")
    c1.metric(
        "Head score",
        f"{head_score:.0f}/100" if head_score is not None else "n/a",
        delta=f"{delta:+.1f}" if delta else None,
    )
    c2.metric("New issues", len(diff["new_issues"]))
    c3.metric("Worse", len(diff["worsened_issues"]))
    c4.metric("Fixed", len(diff["fixed_issues"]))
    if diff.get("deep_categories"):
        st.caption("Investigated with tools on the head: " + ", ".join(diff["deep_categories"]))

    st.dataframe(ui.category_delta_rows(diff), hide_index=True, width="stretch")
    new, worse, fixed = st.tabs(
        [
            f"New ({len(diff['new_issues'])})",
            f"Worse ({len(diff['worsened_issues'])})",
            f"Fixed ({len(diff['fixed_issues'])})",
        ]
    )
    with new:
        for issue in diff["new_issues"]:
            render_issue(issue)
        if not diff["new_issues"]:
            st.success("No new issues.")
    with worse:
        for entry in diff["worsened_issues"]:
            st.caption(f"was {entry['base_severity']}, ×{entry['base_occurrences']}")
            render_issue(entry["issue"])
        if not diff["worsened_issues"]:
            st.success("Nothing got worse.")
    with fixed:
        for issue in diff["fixed_issues"]:
            render_issue(issue)
        if not diff["fixed_issues"]:
            st.info("Nothing was fixed.")

    document = {k: v for k, v in diff.items() if k != "head_report"}
    slug = (repo.get("full_name") or "repository").replace("/", "__")
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download diff JSON",
        json.dumps(document, indent=2, ensure_ascii=False),
        f"drrepo_{slug}_diff.json",
        "application/json",
        width="stretch",
    )
    d2.download_button(
        "Download diff Markdown",
        diff_to_markdown(document),
        f"drrepo_{slug}_diff.md",
        "text/markdown",
        width="stretch",
    )
    if diff.get("head_report"):
        st.markdown("---")
        st.markdown("### Head commit report")
        render_report(diff["head_report"], service, key="head")


# ------------------------------------------------------------------- main ---


def render_form(service: AnalysisService, deep: bool, running: bool) -> None:
    missing = service.config.validate_for_llm()
    mode = st.radio("Mode", MODES, horizontal=True, label_visibility="collapsed")
    comparing = mode == MODES[1]
    with st.form("analyze"):
        repo_url = st.text_input(
            "GitHub repository URL", placeholder="https://github.com/owner/repo"
        )
        if comparing:
            c1, c2 = st.columns(2)
            base = c1.text_input("Base (compare against)", placeholder="main")
            ref = c2.text_input("Head (the change)", placeholder="default branch")
        else:
            base = ""
            ref = st.text_input(
                "Branch, tag, or commit (optional)",
                placeholder="default branch",
                help="A full 40-character SHA pins the exact code that is analyzed.",
            )
        description = st.text_area(
            "Context for the investigators (optional)",
            placeholder="e.g. 'We are about to adopt this library; focus on security and maintenance.'",
            height=80,
        )
        submitted = st.form_submit_button(
            "Compare" if comparing else "Analyze", type="primary", width="stretch", disabled=running
        )

    if not submitted:
        return
    try:
        repo = RepoRef.parse(repo_url)
        pinned = validate_ref(ref) if ref.strip() else None
        if comparing:
            if not base.strip():
                raise ValueError("Compare mode needs a base branch, tag, or commit.")
            base_ref = validate_ref(base)
    except ValueError as e:
        st.error(str(e))
        return
    use_llm = deep and not missing
    st.session_state["job"] = (
        start_compare_job(service, repo.html_url, base_ref, pinned, description, use_llm)
        if comparing
        else start_job(service, repo.html_url, description, use_llm, pinned)
    )
    st.session_state["job_shown"] = False
    st.session_state["view"] = None
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="DrRepo", page_icon="🩺", layout="wide")
    service = get_service()
    deep = render_sidebar(service)

    st.title("🩺 DrRepo")
    st.caption("Agentic health check for public GitHub repositories.")

    missing = service.config.validate_for_llm()
    if missing:
        st.info(
            f"{', '.join(missing)} not set: reports will use automated summaries only "
            "(no LLM narrative or tool-calling investigation)."
        )

    job: AnalysisJob | None = st.session_state.get("job")
    running = job is not None and job.status == "running"
    render_form(service, deep, running)
    render_progress()

    view = st.session_state.get("view")
    if view:
        report = service.latest_report(view)
        if report is not None:
            render_report(report, service)
            return
    job = st.session_state.get("job")
    if job is not None and job.status == "error":
        st.error(f"Analysis failed: {job.error}")
    if job is not None and job.status == "done" and job.result:
        if "diff_schema_version" in job.result:
            render_diff(job.result, service)
        else:
            render_report(job.result, service)


if __name__ == "__main__":  # `streamlit run` executes the script as __main__
    main()
