"""DrRepo Streamlit UI. Launch with `drrepo ui`.

An analysis takes minutes, so it runs on a background thread that writes into a
plain `AnalysisJob` object (not `st.session_state`, which needs a script-run
context the worker thread doesn't have). A fragment re-renders every second to
show live progress and triggers a full rerun when the job finishes.

`AnalysisService` is cached with `st.cache_resource`, i.e. one per Streamlit
*process*: the LLM circuit breaker and dependency cache carry across sessions
and runs, while every run still gets a fresh token budget.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import streamlit as st

from drrepo import __version__
from drrepo.config import Config
from drrepo.interfaces.health import check_all
from drrepo.log import configure_logging, logger
from drrepo.models import RepoRef
from drrepo.recon.clone import validate_ref
from drrepo.report.exporters import to_cyclonedx, to_json, to_markdown, to_sarif
from drrepo.report.synthesis import grade
from drrepo.service import AnalysisService

SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}


@dataclass
class AnalysisJob:
    repo_url: str
    started_at: float = field(default_factory=time.time)
    messages: list[str] = field(default_factory=list)
    status: str = "running"  # running | done | error
    result: dict[str, Any] | None = None
    error: str | None = None


@st.cache_resource
def get_service() -> AnalysisService:
    config = Config.from_env()
    configure_logging(config.log_level)
    return AnalysisService(config)


def start_job(
    service: AnalysisService, repo_url: str, description: str, deep: bool, ref: str | None = None
) -> AnalysisJob:
    job = AnalysisJob(repo_url=repo_url)

    def run() -> None:
        try:
            job.result = service.analyze(
                repo_url, description, deep=deep, progress=job.messages.append, ref=ref
            )
            job.status = "done"
        except Exception as e:
            logger.exception(f"Analysis of {repo_url} failed")
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"

    threading.Thread(target=run, daemon=True, name="drrepo-analysis").start()
    return job


def render_sidebar(service: AnalysisService) -> bool:
    config = service.config
    with st.sidebar:
        st.markdown("### DrRepo")
        st.caption(f"v{__version__} · {config.model_provider} · `{config.model_for()}`")
        deep = st.toggle(
            "Deep investigation",
            value=config.enable_deep_investigation,
            help="Let the Lead Investigator send risky categories to a tool-calling agent. Off = fast, deterministic pass.",
        )
        st.markdown("---")
        st.markdown(
            "**What it checks**\n\n"
            "- Code quality: ruff\n"
            "- Security: bandit, semgrep, secret scan\n"
            "- Dependencies: OSV.dev, deps.dev licenses\n"
            "- Documentation: README structure\n"
            "- Maintainability: tests, CI, activity"
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
                st.caption(
                    f"{name}: {c['status']}" + (f" — {c['detail']}" if c.get("detail") else "")
                )
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
    with st.status(f"Analyzing {job.repo_url} — {elapsed}s", expanded=True):
        for message in job.messages[-12:]:
            st.write(message)


def render_report(result: dict[str, Any]) -> None:
    repo = result.get("repository", {})
    score = float(result.get("overall_score", 0))
    history = result.get("score_history")

    st.markdown(f"## {repo.get('full_name') or repo.get('name')}")
    if repo.get("description"):
        st.caption(repo["description"])
    if repo.get("commit_sha"):
        at = f" on `{repo['ref']}`" if repo.get("ref") else ""
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
        label = ("🕵️ " if cs.get("investigation_depth") == "deep" else "") + name.replace(
            "_", " "
        ).title()
        if cs.get("assessed", True):
            col.metric(
                label,
                f"{cs['score']:.0f}",
                delta=f"{deltas[name]:+.1f}" if name in deltas else None,
            )
        else:
            col.metric(
                label,
                "n/a",
                help="Not assessable for this repository; excluded from the overall score.",
            )

    tab_summary, tab_issues, tab_trace, tab_raw = st.tabs(
        ["Summary", "Issues", "How it investigated", "Raw data"]
    )

    with tab_summary:
        for name, cs in categories.items():
            st.markdown(
                f"**{name.replace('_', ' ').title()}** · {cs.get('investigation_depth', 'shallow')}"
            )
            st.write(cs.get("summary", ""))
            for note in cs.get("notes", []):
                st.caption(f"ℹ️ {note}")
        if result.get("quick_wins"):
            st.markdown("#### Quick wins")
            for win in result["quick_wins"]:
                st.markdown(f"- {win}")

    with tab_issues:
        issues = result.get("issues", [])
        severities = st.multiselect("Severity", list(SEVERITY_ICON), default=list(SEVERITY_ICON))
        cats = st.multiselect("Category", list(categories), default=list(categories))
        shown = [i for i in issues if i["severity"] in severities and i["category"] in cats]
        st.caption(f"Showing {min(len(shown), 100)} of {len(shown)} matching issues")
        for issue in shown[:100]:
            location = f" — `{issue['file']}:{issue['line']}`" if issue.get("file") else ""
            times = f" ×{issue['occurrences']}" if issue.get("occurrences", 1) > 1 else ""
            with st.expander(
                f"{SEVERITY_ICON.get(issue['severity'], '⚪')} {issue['title']}{times}{location}"
            ):
                st.markdown(issue.get("description", ""))
                st.markdown(f"**Fix:** {issue.get('recommendation', '')}")
                st.caption(
                    f"{issue['category']} · source: {issue.get('source')} · rule: {issue.get('rule_id') or '—'}"
                )
                extra = issue.get("locations", [])[1:]
                if extra:
                    st.caption(
                        "Also at: "
                        + ", ".join(f"{loc['file']}:{loc.get('line')}" for loc in extra[:10])
                    )
        if not shown:
            st.success("No matching issues.")

    with tab_trace:
        plan = result.get("investigation_plan", {})
        if plan:
            st.markdown("#### Lead Investigator's plan")
            for name, p in plan.items():
                st.markdown(f"- **{name}** → `{p.get('depth')}`: {p.get('rationale')}")
        for name, cs in categories.items():
            trace = cs.get("investigation_trace", [])
            if not trace:
                continue
            with st.expander(f"{name.replace('_', ' ').title()} — {len(trace)} tool calls"):
                for call in trace:
                    st.markdown(f"**`{call['tool']}`** `{json.dumps(call['tool_input'])[:200]}`")
                    st.code(call["observation"], language="text")
        if result.get("llm_usage"):
            st.caption(f"LLM usage this run: {result['llm_usage']}")

    with tab_raw:
        st.markdown("#### Collector status")
        st.dataframe(
            [{"collector": n, **s} for n, s in result.get("collector_status", {}).items()],
            hide_index=True,
            width="stretch",
        )
        st.json(result, expanded=False)

    slug = (repo.get("full_name") or repo.get("name") or "report").replace("/", "__")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button(
        "Download JSON", to_json(result), f"drrepo_{slug}.json", "application/json", width="stretch"
    )
    d2.download_button(
        "Download Markdown",
        to_markdown(result),
        f"drrepo_{slug}.md",
        "text/markdown",
        width="stretch",
    )
    d3.download_button(
        "Download SARIF",
        to_sarif(result),
        f"drrepo_{slug}.sarif",
        "application/sarif+json",
        width="stretch",
    )
    d4.download_button(
        "Download SBOM",
        to_cyclonedx(result),
        f"drrepo_{slug}.cdx.json",
        "application/vnd.cyclonedx+json",
        width="stretch",
    )


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
            "(no LLM narrative or deep investigation)."
        )

    job: AnalysisJob | None = st.session_state.get("job")
    running = job is not None and job.status == "running"

    with st.form("analyze"):
        repo_url = st.text_input(
            "GitHub repository URL", placeholder="https://github.com/owner/repo"
        )
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
            "Analyze", type="primary", width="stretch", disabled=running
        )

    if submitted:
        try:
            repo = RepoRef.parse(repo_url)
            pinned = validate_ref(ref) if ref.strip() else None
        except ValueError as e:
            st.error(str(e))
        else:
            st.session_state["job"] = start_job(
                service, repo.html_url, description, deep and not missing, pinned
            )
            st.session_state["job_shown"] = False
            st.rerun()

    render_progress()

    job = st.session_state.get("job")
    if job is not None and job.status == "error":
        st.error(f"Analysis failed: {job.error}")
    if job is not None and job.status == "done" and job.result:
        render_report(job.result)


if __name__ == "__main__":  # `streamlit run` executes the script as __main__
    main()
