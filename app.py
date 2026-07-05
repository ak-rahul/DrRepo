"""DrRepo v2 Streamlit application.

Analysis now involves cloning + running static analysis tools, so it takes
noticeably longer than v1's pure-API-call flow. The job runs in a background
thread and the UI polls `st.session_state` for progress instead of blocking
the whole page on a single synchronous call.
"""

import threading
import time
from datetime import datetime

import streamlit as st

from src.config import Config
from src.graph.workflow import Workflow
from src.report.exporters import to_json, to_markdown, to_sarif
from src.utils.health_check import HealthChecker
from src.utils.logger import logger

st.set_page_config(
    page_title="DrRepo - Repository Health Specialist",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .main-header {
        font-size: 3rem; font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text; margin: 0; padding: 0;
    }
    .sub-header { font-size: 1.1rem; color: #718096; margin: 0.3rem 0 1.5rem 0; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<h1 class="main-header">🩺 DrRepo</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">AI-Powered Repository Health Analysis — now with real code scanning</p>',
    unsafe_allow_html=True,
)


@st.cache_resource
def get_config() -> Config:
    return Config.from_env()


config = get_config()

# Sidebar
with st.sidebar:
    st.markdown("### 📋 About")
    st.markdown("""
    DrRepo clones your repository and runs:
    - 🔍 Static analysis (ruff, semgrep)
    - 🔒 Security & secret scanning (bandit)
    - 📦 Dependency vulnerability audit (OSV.dev)
    - 📄 README/documentation quality
    - 🏗️ Maintainability signals
    """)
    st.caption("Only public repositories are supported. Code is parsed, never executed.")

    st.markdown("---")
    st.markdown("### ⚙️ Configuration")
    st.code(f"{config.model_provider.upper()} • {config.model_name}", language="")

    st.markdown("---")
    st.markdown("### 🏥 System Health")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    @st.cache_data(ttl=30)
    def _cached_health():
        return HealthChecker.check_all(config)

    with st.spinner("Checking..."):
        health_status = _cached_health()

    if health_status["status"] == "healthy":
        st.success("✅ All Systems OK")
    else:
        st.warning("⚠️ Degraded")

    for name, details in health_status.get("components", {}).items():
        icon = "✅" if details.get("status") in ("up", "not_used") else "❌"
        st.text(f"{icon} {name}: {details.get('status')}")

    st.markdown("---")
    st.markdown("### 📚 Links")
    st.markdown(
        "[Docs](https://github.com/ak-rahul/DrRepo) • [Issues](https://github.com/ak-rahul/DrRepo/issues)"
    )


# Main content
st.markdown("### 🚀 Analyze Repository")

with st.form("analysis_form"):
    repo_url = st.text_input(
        "GitHub Repository URL", placeholder="https://github.com/username/repository"
    )
    description = st.text_area("Description (Optional)", placeholder="Brief context...", height=80)
    analyze_button = st.form_submit_button("🔍 Analyze", use_container_width=True, type="primary")


def _run_analysis_in_background(repo_url: str, description: str):
    """Runs on a background thread; writes progress/result into session_state."""
    try:
        st.session_state["analysis_status"] = "Cloning and analyzing... this can take 1-3 minutes"
        workflow = Workflow(config)
        result = workflow.execute(repo_url, description)
        st.session_state["analysis_result"] = result
        st.session_state["analysis_status"] = "done"
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        st.session_state["analysis_error"] = str(e)
        st.session_state["analysis_status"] = "error"


if analyze_button:
    if not repo_url:
        st.error("⚠️ Enter a GitHub repository URL")
    elif not repo_url.startswith("https://github.com/"):
        st.error("❌ Invalid URL format")
    else:
        missing = config.validate_for_llm()
        if missing:
            st.error(f"❌ Missing configuration: {', '.join(missing)}")
            st.stop()

        st.session_state["analysis_result"] = None
        st.session_state["analysis_error"] = None
        st.session_state["analysis_status"] = "running"
        thread = threading.Thread(
            target=_run_analysis_in_background, args=(repo_url, description), daemon=True
        )
        thread.start()

if st.session_state.get("analysis_status") == "running":
    with st.spinner(st.session_state.get("analysis_status_text", "Analyzing...")):
        while st.session_state.get("analysis_status") == "running":
            time.sleep(1)
    st.rerun()

if st.session_state.get("analysis_status") == "error":
    st.error("❌ **Analysis Failed**")
    st.error(st.session_state.get("analysis_error", "Unknown error"))

result = st.session_state.get("analysis_result")
if result:
    st.markdown("---")
    st.markdown("### 📊 Results")

    repo = result.get("repository", {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Overall Score", f"{result.get('overall_score', 0):.0f}/100")
    col2.metric("Stars", f"{repo.get('stars', 0):,}")
    col3.metric("Forks", f"{repo.get('forks', 0):,}")
    col4.metric("Issues Found", len(result.get("issues", [])))

    st.markdown("#### Category Scores")
    category_scores = result.get("category_scores", {})
    cat_cols = st.columns(max(len(category_scores), 1))
    # strict=False: if an analyst category is ever missing (e.g. a failed run),
    # display whatever categories are present rather than crashing the page.
    for col, (name, cs) in zip(cat_cols, category_scores.items(), strict=False):
        label = name.replace("_", " ").title()
        if cs.get("investigation_depth") == "deep":
            label = f"🕵️ {label}"
        col.metric(label, f"{cs['score']:.0f}/100")

    deep_categories = {
        name: cs for name, cs in category_scores.items() if cs.get("investigation_depth") == "deep"
    }
    if deep_categories:
        st.markdown("---")
        st.markdown("### 🕵️ How It Investigated This")
        st.caption(
            "These categories were flagged by the Lead Investigator for a deeper, "
            "tool-calling investigation rather than a quick pass over recon data."
        )
        for name, cs in deep_categories.items():
            with st.expander(
                f"{name.replace('_', ' ').title()} — {len(cs.get('investigation_trace', []))} tool calls"
            ):
                for call in cs.get("investigation_trace", []):
                    st.markdown(f"**{call['tool']}**`({call['tool_input']})`")
                    st.code(call["observation"], language="text")

    st.markdown("---")
    st.markdown("### 📝 Issues")
    issues = result.get("issues", [])
    if issues:
        for i, issue in enumerate(issues[:25], 1):
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                issue["severity"], "⚪"
            )
            location = f" — {issue['file']}:{issue['line']}" if issue.get("file") else ""
            with st.expander(
                f"{icon} {i}. [{issue['severity'].upper()}] {issue['title']}{location}"
            ):
                st.markdown(f"**Description:** {issue['description']}")
                st.markdown(f"**Recommendation:** {issue['recommendation']}")
                if issue.get("source"):
                    st.caption(f"Source: {issue['source']}")
    else:
        st.success("✨ No issues found!")

    st.markdown("---")
    col_json, col_md, col_sarif = st.columns(3)
    with col_json:
        st.download_button(
            "📥 Download JSON Report",
            to_json(result),
            f"drrepo_{repo.get('name', 'report')}.json",
            "application/json",
            use_container_width=True,
        )
    with col_md:
        st.download_button(
            "📥 Download Markdown Report",
            to_markdown(result),
            f"drrepo_{repo.get('name', 'report')}.md",
            "text/markdown",
            use_container_width=True,
        )
    with col_sarif:
        st.download_button(
            "📥 Download SARIF (GitHub code scanning)",
            to_sarif(result),
            f"drrepo_{repo.get('name', 'report')}.sarif",
            "application/sarif+json",
            use_container_width=True,
        )

st.markdown("---")
st.caption(f"DrRepo v2 • {datetime.now().year}")
