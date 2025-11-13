"""Streamlit frontend for DrRepo."""
import streamlit as st
import json
from datetime import datetime
from src.main import PublicationAssistant

# Page configuration
st.set_page_config(
    page_title="DrRepo",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .subtitle {
        text-align: center;
        color: #666;
        font-size: 1.2rem;
        margin-top: 0;
        margin-bottom: 2rem;
    }
    .stButton>button {
        width: 100%;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: bold;
        border: none;
        padding: 0.75rem;
        border-radius: 8px;
        font-size: 1.1rem;
    }
    .stButton>button:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'analyzing' not in st.session_state:
    st.session_state.analyzing = False
if 'assistant' not in st.session_state:
    st.session_state.assistant = None

# Sidebar
with st.sidebar:
    st.markdown("# 🩺 About DrRepo")
    
    st.info("""
    **DrRepo** - Your Repository's Health Specialist
    
    Multi-agent AI platform that analyzes GitHub repositories 
    and provides actionable recommendations.
    """)
    
    st.markdown("### 🤖 AI Agents")
    st.markdown("""
    1. 🔍 **Repo Analyzer**  
       *Analyzes structure & metadata*
    
    2. 🏷️ **Metadata Recommender**  
       *Optimizes discoverability*
    
    3. ✍️ **Content Improver**  
       *Enhances README quality*
    
    4. ✅ **Reviewer Critic**  
       *Quality assessment*
    
    5. 🔎 **Fact Checker**  
       *Verifies claims with RAG*
    """)
    
    st.markdown("---")
    st.markdown("### ⚙️ Settings")
    st.markdown("""
    **Analysis Time:** ~30-60 sec  
    **Privacy:** Local processing  
    **Cost:** Free (Groq API)
    """)

# Header
st.markdown('<h1 class="main-header">🩺 DrRepo</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Your Repository\'s Health Specialist</p>', unsafe_allow_html=True)

# Main content
st.markdown("### 📝 Repository Information")

col1, col2 = st.columns([3, 1])

with col1:
    repo_url = st.text_input(
        "🔗 GitHub Repository URL",
        placeholder="https://github.com/username/repository",
        help="Enter the full URL of any public GitHub repository"
    )

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    analyze_button = st.button(
        "🚀 Analyze",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.analyzing
    )

description = st.text_area(
    "📝 Description (Optional)",
    placeholder="Brief description to improve analysis quality",
    height=100
)

# Examples
with st.expander("📚 Try Example Repositories"):
    col1, col2, col3 = st.columns(3)
    
    if col1.button("🔹 requests", use_container_width=True):
        st.session_state.example_url = "https://github.com/psf/requests"
        st.rerun()
    
    if col2.button("🔹 django", use_container_width=True):
        st.session_state.example_url = "https://github.com/django/django"
        st.rerun()
    
    if col3.button("🔹 fastapi", use_container_width=True):
        st.session_state.example_url = "https://github.com/fastapi/fastapi"
        st.rerun()

st.markdown("---")

# Analysis logic
if analyze_button and repo_url:
    if not repo_url.startswith('https://github.com/'):
        st.error("❌ Please enter a valid GitHub URL")
    else:
        st.session_state.analyzing = True
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            status_text.text("🔄 Initializing AI agents...")
            progress_bar.progress(10)
            
            if st.session_state.assistant is None:
                st.session_state.assistant = PublicationAssistant()
            
            status_text.text("🔍 Analyzing repository...")
            progress_bar.progress(30)
            
            result = st.session_state.assistant.analyze(repo_url, description)
            
            progress_bar.progress(90)
            status_text.text("✅ Complete!")
            
            st.session_state.analysis_result = result
            st.session_state.analyzing = False
            
            progress_bar.progress(100)
            st.success('✅ Analysis complete!')
            st.balloons()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.session_state.analyzing = False

# Display results
if st.session_state.analysis_result:
    result = st.session_state.analysis_result
    
    st.markdown("---")
    st.markdown("## 📊 Analysis Report")
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    score = result['repository']['current_score']
    
    with col1:
        st.metric("Quality Score", f"{score:.1f}/100")
    
    with col2:
        status = result['summary']['status']
        st.metric("Status", status)
    
    with col3:
        st.metric("Total Suggestions", result['summary']['total_suggestions'])
    
    with col4:
        st.metric("Critical Issues", result['summary']['critical_issues'])
    
    st.markdown("---")
    
    # Action items
    st.markdown("### 🎯 Priority Action Items")
    
    for i, item in enumerate(result.get('action_items', [])[:5], 1):
        priority = item.get('priority', 'Medium')
        emoji = "🔴" if priority == "High" else "🟡"
        
        with st.expander(f"{emoji} {priority} - {item.get('action', 'N/A')}", expanded=(i <= 2)):
            st.markdown(f"**Category:** {item.get('category', 'N/A')}")
            st.markdown(f"**Impact:** {item.get('impact', 'N/A')}")
    
    # Download
    json_str = json.dumps(result, indent=2)
    st.download_button(
        label="📥 Download Full Report (JSON)",
        data=json_str,
        file_name=f"drrepo_{result['repository']['name']}_{datetime.now().strftime('%Y%m%d')}.json",
        mime="application/json"
    )

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666;">
    <strong>DrRepo 🩺</strong> | Your Repository's Health Specialist<br>
    Powered by LangGraph, Groq, and Multi-Agent AI
</div>
""", unsafe_allow_html=True)
