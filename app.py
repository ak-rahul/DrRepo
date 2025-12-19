"""DrRepo Streamlit Application."""

import streamlit as st
import json
from datetime import datetime

from src.main import PublicationAssistant
from src.utils.config import config
from src.utils.logger import logger
from src.utils.health_check import HealthChecker
from src.utils.exceptions import (
    RepositoryNotFoundError,
    RateLimitError,
    APIConnectionError,
    ValidationError,
    ConfigurationError,
    ToolExecutionError,
    AgentExecutionError
)


# Page configuration
st.set_page_config(
    page_title="DrRepo - Repository Health Specialist",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)


st.markdown("""
<style>
    /* Remove top padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Clean header */
    .main-header {
        font-size: 3rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0;
        padding: 0;
    }
    
    .sub-header {
        font-size: 1.1rem;
        color: #718096;
        margin: 0.3rem 0 1.5rem 0;
    }
    
    /* Sidebar - Same as main background */
    [data-testid="stSidebar"] {
        background-color: transparent;
    }
    
    [data-testid="stSidebar"] > div:first-child {
        background-color: transparent;
    }
    
    /* Button hover effect */
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# Clean, Minimal Header
st.markdown('<h1 class="main-header">🩺 DrRepo</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">AI-Powered Repository Health Analysis</p>', unsafe_allow_html=True)


# Sidebar
with st.sidebar:
    st.markdown("### 📋 About")
    st.markdown("""
    5 AI agents analyze your repository:
    - 🔍 Structure Analysis
    - 🏷️ Metadata Optimization
    - ✍️ Content Enhancement
    - ✅ Quality Assessment
    - 🔎 Fact Checking
    """)
    
    st.markdown("---")
    st.markdown("### ⚙️ Configuration")
    st.code(f"{config.model_provider.upper()} • {config.model_name}", language="")
    
    # Health Check Section
    st.markdown("---")
    st.markdown("### 🏥 System Health")
    
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()
    
    with st.spinner("Checking..."):
        health_status = HealthChecker.check_all()
    
    overall_status = health_status["status"]
    if overall_status == "healthy":
        st.success("✅ All Systems OK")
    else:
        st.warning("⚠️ Degraded")
    
    components = health_status.get("components", {})
    
    # LLM Status
    llm_key = f"llm_{config.model_provider}"
    if llm_key in components:
        llm_status = components[llm_key]
        icon = "✅" if llm_status.get("status") == "up" else "❌"
        latency = llm_status.get("latency_ms", "N/A")
        st.text(f"{icon} LLM: {latency}ms")
    
    # GitHub API
    if "github_api" in components:
        gh = components["github_api"]
        icon = "✅" if gh.get("status") in ["up", "degraded"] else "❌"
        limit = gh.get("rate_limit_remaining", "N/A")
        st.text(f"{icon} GitHub: {limit} calls")
    
    # Tavily API
    if "tavily_api" in components:
        tv = components["tavily_api"]
        icon = "✅" if tv.get("status") == "up" else "❌"
        st.text(f"{icon} Tavily: OK")
    
    # RAG
    if "rag_retriever" in components:
        rag = components["rag_retriever"]
        icon = "✅" if rag.get("status") == "up" else "❌"
        st.text(f"{icon} RAG: OK")
    
    st.caption(f"Updated: {datetime.fromisoformat(health_status['timestamp']).strftime('%H:%M:%S')}")
    
    # Errors
    failed = {k: v for k, v in components.items() if v.get("status") == "down"}
    if failed:
        with st.expander("🔍 Errors"):
            for comp, details in failed.items():
                st.error(f"{comp}: {details.get('error', 'Unknown')}")
    
    st.markdown("---")
    st.markdown("### 📚 Links")
    st.markdown("[Docs](https://github.com/ak-rahul/DrRepo) • [Issues](https://github.com/ak-rahul/DrRepo/issues)")


# Main Content - Input Section (Top Priority)
st.markdown("### 🚀 Analyze Repository")

with st.form("analysis_form"):
    repo_url = st.text_input(
        "GitHub Repository URL",
        placeholder="https://github.com/username/repository"
    )
    
    description = st.text_area(
        "Description (Optional)",
        placeholder="Brief description to improve analysis...",
        height=80
    )
    
    analyze_button = st.form_submit_button(
        "🔍 Analyze",
        use_container_width=True,
        type="primary"
    )


# Analysis Execution
if analyze_button:
    if not repo_url:
        st.error("⚠️ Enter a GitHub repository URL")
    elif not repo_url.startswith("https://github.com/"):
        st.error("❌ Invalid URL format")
    else:
        if not config.validate():
            st.error("❌ Missing API keys in .env file")
            st.stop()
        
        try:
            progress = st.progress(0)
            status = st.empty()
            
            status.text("🔧 Initializing...")
            progress.progress(10)
            assistant = PublicationAssistant()
            
            status.text("🔍 Analyzing... (30-60 seconds)")
            progress.progress(30)
            
            result = assistant.analyze(
                repo_url=repo_url,
                description=description if description else None
            )
            
            progress.progress(100)
            status.text("✅ Complete!")
            
            st.success("🎉 Analysis complete!")
            
            # Results
            st.markdown("---")
            st.markdown("### 📊 Results")
            
            repo = result.get("repository", {})
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Quality", f"{repo.get('current_score', 0)}/100")
            col2.metric("Stars", f"{repo.get('stars', 0):,}")
            col3.metric("Forks", f"{repo.get('forks', 0):,}")
            
            status_val = result.get("summary", {}).get("status", "Unknown")
            status_icon = {"Excellent": "🟢", "Good": "🟡", "Needs Improvement": "🟠", "Poor": "🔴"}.get(status_val, "⚪")
            col4.metric("Status", f"{status_icon} {status_val}")
            
            # Actions
            st.markdown("---")
            st.markdown("### 📝 Actions")
            
            actions = result.get("action_items", [])
            
            if actions:
                for i, item in enumerate(actions[:10], 1):
                    priority = item.get("priority", "Medium")
                    icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(priority, "⚪")
                    
                    with st.expander(f"{icon} {i}. {item.get('action', 'Action')}"):
                        st.markdown(f"**Category:** {item.get('category', 'N/A')}")
                        st.markdown(f"**Priority:** {priority}")
                        st.markdown(f"**Impact:** {item.get('impact', 'N/A')}")
            else:
                st.success("✨ No action items - repository looks great!")
            
            # Download
            st.markdown("---")
            json_str = json.dumps(result, indent=2)
            st.download_button(
                "📥 Download Report (JSON)",
                json_str,
                f"drrepo_{repo.get('name', 'report')}.json",
                "application/json",
                use_container_width=True
            )
        
        except ValidationError as e:
            st.error("❌ **Validation Error**")
            st.error(str(e))
            st.info("💡 Check URL format: https://github.com/owner/repo")
            
        except RepositoryNotFoundError as e:
            st.error("❌ **Repository Not Found**")
            st.error(str(e))
            st.info("💡 Verify URL and repository visibility")
            
        except RateLimitError as e:
            st.error("❌ **Rate Limit Exceeded**")
            st.error(str(e))
            if hasattr(e, 'retry_after') and e.retry_after:
                st.warning(f"⏰ Wait {e.retry_after // 60} minutes")
            
        except APIConnectionError as e:
            st.error("❌ **API Connection Error**")
            st.error(str(e))
            st.info("💡 Check internet and API keys")
            
        except ConfigurationError as e:
            st.error("❌ **Configuration Error**")
            st.error(str(e))
            st.info("💡 Add API keys to .env file")
            
        except ToolExecutionError as e:
            st.error(f"❌ **Tool Error: {e.tool_name}**")
            st.error(str(e))
            with st.expander("Details"):
                st.code(str(e))
            
        except AgentExecutionError as e:
            st.error(f"❌ **Agent Error: {e.agent_name}**")
            st.error(str(e))
            with st.expander("Details"):
                st.code(str(e))
        
        except Exception as e:
            st.error("❌ **Unexpected Error**")
            st.error(str(e))
            with st.expander("Details"):
                st.code(f"{type(e).__name__}\n{str(e)}")


# Footer
st.markdown("---")
st.caption("Made with ❤️ by [AK Rahul](https://github.com/ak-rahul) • DrRepo v1.0")
