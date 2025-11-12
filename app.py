"""Streamlit frontend for Publication Assistant."""
import streamlit as st
import json
from datetime import datetime
from src.main import PublicationAssistant

# Page configuration
st.set_page_config(
    page_title="Publication Assistant",
    page_icon="📊",
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
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .success-box {
        background: #d4edda;
        border-left: 4px solid #28a745;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .warning-box {
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .error-box {
        background: #f8d7da;
        border-left: 4px solid #dc3545;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
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
    div[data-testid="stExpander"] {
        background: #f8f9fa;
        border-radius: 8px;
        border: 1px solid #dee2e6;
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
    st.image("https://cdn-icons-png.flaticon.com/512/2103/2103633.png", width=100)
    st.markdown("# 📊 About")
    
    st.info("""
    **Publication Assistant** uses 5 specialized AI agents to analyze 
    GitHub repositories and provide comprehensive, actionable recommendations.
    """)
    
    st.markdown("### 🤖 AI Agents")
    st.markdown("""
    1. 🔍 **Repo Analyzer**  
       *Structure & metadata analysis*
    
    2. 🏷️ **Metadata Recommender**  
       *Tags & description optimization*
    
    3. ✍️ **Content Improver**  
       *README enhancement suggestions*
    
    4. ✅ **Reviewer Critic**  
       *Quality assessment & gaps*
    
    5. 🔎 **Fact Checker**  
       *Claims verification with RAG*
    """)
    
    st.markdown("---")
    
    st.markdown("### 📚 How to Use")
    st.markdown("""
    1. Enter GitHub repository URL
    2. Add optional description
    3. Click **Analyze Repository**
    4. View comprehensive report
    5. Download JSON results
    """)
    
    st.markdown("---")
    
    st.markdown("### ⚙️ Settings")
    st.markdown("""
    **Analysis Time:** ~30-60 seconds  
    **Privacy:** Local processing  
    **Cost:** Free (using Groq)
    """)

# Header
st.markdown('<h1 class="main-header">📊 Publication Assistant</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">AI-Powered GitHub Repository Analyzer</p>', unsafe_allow_html=True)

# Main content
tab1, tab2 = st.tabs(["🔍 Analyze", "ℹ️ Info"])

with tab1:
    # Input section
    st.markdown("### 📝 Repository Information")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        repo_url = st.text_input(
            "🔗 GitHub Repository URL",
            placeholder="https://github.com/username/repository",
            help="Enter the full URL of any public GitHub repository",
            key="repo_url"
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
        placeholder="Brief description of the project to improve analysis quality",
        height=100,
        help="Providing context helps improve recommendations"
    )
    
    # Examples
    with st.expander("📚 Try Example Repositories"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔹 requests", use_container_width=True):
                st.session_state.example_url = "https://github.com/psf/requests"
                st.session_state.example_desc = "Popular Python HTTP library"
                st.rerun()
        
        with col2:
            if st.button("🔹 django", use_container_width=True):
                st.session_state.example_url = "https://github.com/django/django"
                st.session_state.example_desc = "Python web framework"
                st.rerun()
        
        with col3:
            if st.button("🔹 fastapi", use_container_width=True):
                st.session_state.example_url = "https://github.com/fastapi/fastapi"
                st.session_state.example_desc = "Modern Python web framework"
                st.rerun()
    
    # Handle examples
    if 'example_url' in st.session_state:
        repo_url = st.session_state.example_url
        description = st.session_state.example_desc
        del st.session_state.example_url
        del st.session_state.example_desc
    
    st.markdown("---")
    
    # Analysis logic
    if analyze_button and repo_url:
        if not repo_url.startswith('https://github.com/'):
            st.error("❌ Please enter a valid GitHub URL (https://github.com/...)")
        else:
            st.session_state.analyzing = True
            
            # Progress indicators
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                # Initialize assistant
                status_text.text("🔄 Initializing AI agents...")
                progress_bar.progress(10)
                
                if st.session_state.assistant is None:
                    st.session_state.assistant = PublicationAssistant()
                
                # Run analysis
                status_text.text("🔍 Analyzing repository (this may take 30-60 seconds)...")
                progress_bar.progress(30)
                
                result = st.session_state.assistant.analyze(repo_url, description or "")
                
                progress_bar.progress(90)
                status_text.text("✅ Analysis complete!")
                
                st.session_state.analysis_result = result
                st.session_state.analyzing = False
                
                progress_bar.progress(100)
                st.success('✅ Analysis complete!')
                st.balloons()
                
            except Exception as e:
                st.error(f"❌ Error during analysis: {str(e)}")
                with st.expander("🔍 Error Details"):
                    st.code(str(e))
                st.session_state.analyzing = False
                progress_bar.empty()
                status_text.empty()

    # Display results
    if st.session_state.analysis_result:
        result = st.session_state.analysis_result
        
        st.markdown("---")
        st.markdown("## 📊 Analysis Report")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        score = result['repository']['current_score']
        score_emoji = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"
        
        with col1:
            st.metric(
                "Quality Score",
                f"{score:.1f}/100",
                delta=None,
                help="Overall documentation quality"
            )
        
        with col2:
            status = result['summary']['status']
            status_emoji = "🟢" if status == "Good" else "🟡" if status == "Needs Improvement" else "🔴"
            st.metric(
                "Status",
                f"{status_emoji} {status}",
                help="Current repository status"
            )
        
        with col3:
            st.metric(
                "Total Suggestions",
                result['summary']['total_suggestions'],
                help="Number of recommendations"
            )
        
        with col4:
            st.metric(
                "Critical Issues",
                result['summary']['critical_issues'],
                delta=None if result['summary']['critical_issues'] == 0 else f"-{result['summary']['critical_issues']}",
                delta_color="inverse",
                help="High-priority issues"
            )
        
        st.markdown("---")
        
        # Repository info
        st.markdown("### 📦 Repository Information")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Name:** {result['repository']['name']}")
            st.markdown(f"**URL:** [{result['repository']['url']}]({result['repository']['url']})")
        
        with col2:
            st.markdown(f"**Quality Score:** {score:.1f}/100 {score_emoji}")
            st.markdown(f"**Status:** {status_emoji} {status}")
        
        st.markdown("---")
        
        # Action items
        st.markdown("### 🎯 Priority Action Items")
        
        action_items = result.get('action_items', [])
        if action_items:
            for i, item in enumerate(action_items[:5], 1):
                priority = item.get('priority', 'Medium')
                priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🟢"
                
                with st.expander(f"{priority_emoji} **{priority}** - {item.get('action', 'N/A')}", expanded=(i <= 2)):
                    st.markdown(f"**Category:** {item.get('category', 'N/A')}")
                    st.markdown(f"**Impact:** {item.get('impact', 'N/A')}")
                    st.markdown(f"**Action:** {item.get('action', 'N/A')}")
        else:
            st.info("No critical action items - great job! 🎉")
        
        st.markdown("---")
        
        # Detailed sections
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🏷️ Metadata",
            "✍️ Content",
            "✅ Quality Review",
            "🔎 Fact Check",
            "📥 Export"
        ])
        
        with tab1:
            st.markdown("### Metadata Recommendations")
            metadata = result.get('metadata', {})
            suggestions = metadata.get('suggestions', [])
            
            if suggestions:
                for i, sugg in enumerate(suggestions[:5], 1):
                    if isinstance(sugg, dict):
                        st.info(f"**{i}.** {sugg.get('recommendation', str(sugg))}")
                    else:
                        st.info(f"**{i}.** {str(sugg)}")
            else:
                st.success("Metadata looks good! ✅")
        
        with tab2:
            st.markdown("### Content Improvements")
            content = result.get('content', {})
            
            # Missing sections
            missing = content.get('missing_sections', [])
            if missing:
                st.warning("**❌ Missing Sections:**")
                for section in missing:
                    st.markdown(f"- {section}")
            else:
                st.success("All essential sections present! ✅")
            
            st.markdown("---")
            
            # Improvements
            improvements = content.get('improvements', [])
            if improvements:
                st.info("**💡 Suggested Improvements:**")
                for i, imp in enumerate(improvements[:5], 1):
                    if isinstance(imp, dict):
                        st.markdown(f"{i}. {imp.get('improvement', str(imp))}")
                    else:
                        st.markdown(f"{i}. {str(imp)}")
        
        with tab3:
            st.markdown("### Quality Review")
            quality = result.get('quality_review', {})
            
            if quality.get('checklist'):
                checklist = quality['checklist']
                st.markdown("**📋 Completeness Checklist:**")
                
                col1, col2 = st.columns(2)
                items = list(checklist.items())
                mid = len(items) // 2
                
                with col1:
                    for key, value in items[:mid]:
                        emoji = "✅" if value else "❌"
                        st.markdown(f"{emoji} {key.replace('_', ' ').title()}")
                
                with col2:
                    for key, value in items[mid:]:
                        emoji = "✅" if value else "❌"
                        st.markdown(f"{emoji} {key.replace('_', ' ').title()}")
            
            # Feedback
            feedback = quality.get('feedback', [])
            if feedback:
                st.markdown("---")
                st.markdown("**💬 Reviewer Feedback:**")
                for fb in feedback[:3]:
                    if isinstance(fb, dict):
                        st.info(fb.get('comment', str(fb)))
                    else:
                        st.info(str(fb))
        
        with tab4:
            st.markdown("### Fact Check Results")
            fact_check = result.get('fact_check', {})
            
            verified = fact_check.get('verified', 0)
            st.metric("Claims Verified", verified)
            
            results = fact_check.get('results', [])
            if results:
                st.markdown("**🔍 Verification Details:**")
                for fc_result in results[:5]:
                    if isinstance(fc_result, dict):
                        verified_status = fc_result.get('verified', False)
                        emoji = "✅" if verified_status else "⚠️"
                        st.markdown(f"{emoji} {fc_result.get('finding', str(fc_result))}")
                    else:
                        st.markdown(f"- {str(fc_result)}")
        
        with tab5:
            st.markdown("### Export Results")
            
            # JSON download
            json_str = json.dumps(result, indent=2)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"analysis_{result['repository']['name']}_{timestamp}.json"
            
            st.download_button(
                label="📥 Download Full Report (JSON)",
                data=json_str,
                file_name=filename,
                mime="application/json",
                use_container_width=True
            )
            
            st.markdown("---")
            
            # Preview JSON
            with st.expander("👁️ Preview JSON"):
                st.json(result)

with tab2:
    st.markdown("### ℹ️ About Publication Assistant")
    
    st.markdown("""
    **Publication Assistant** is an AI-powered tool that helps improve GitHub repository documentation 
    using a multi-agent system built with LangGraph.
    
    #### 🏗️ Architecture
    
    The system uses **5 specialized AI agents** working in sequence:
    
    1. **🔍 Repo Analyzer** - Analyzes repository structure, metadata, and code organization
    2. **🏷️ Metadata Recommender** - Suggests improvements for tags, topics, and descriptions
    3. **✍️ Content Improver** - Provides README enhancement recommendations
    4. **✅ Reviewer Critic** - Performs comprehensive quality assessment
    5. **🔎 Fact Checker** - Verifies claims using RAG (Retrieval-Augmented Generation)
    
    #### 🛠️ Technology Stack
    
    - **LangGraph** - Multi-agent orchestration
    - **Groq** - Fast LLM inference (llama-3.3-70b)
    - **LangChain** - Agent framework
    - **FAISS** - Vector search for RAG
    - **Streamlit** - Web interface
    - **GitHub API** - Repository data
    - **Tavily** - Web search
    
    #### 📊 Features
    
    - ✅ Comprehensive repository analysis
    - ✅ AI-powered recommendations
    - ✅ Quality scoring (0-100)
    - ✅ Priority action items
    - ✅ Fact-checking with RAG
    - ✅ JSON export
    - ✅ Free to use (Groq API)
    
    #### 🚀 How It Works
    
    1. **Input** - You provide a GitHub repository URL
    2. **Fetch** - System retrieves repository data via GitHub API
    3. **Analyze** - Each agent performs specialized analysis
    4. **Synthesize** - Results are combined into comprehensive report
    5. **Output** - Actionable recommendations with priority rankings
    
    #### 💡 Tips for Best Results
    
    - Use repositories with existing README files
    - Provide context in the description field
    - Review all tabs for complete insights
    - Download JSON for detailed analysis
    
    #### 📝 License & Credits
    
    Built for educational and open-source purposes.  
    Powered by modern AI and open-source tools.
    """)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 2rem;">
    <strong>Publication Assistant</strong> | Powered by LangGraph 🦜, Groq 🚀, and Multi-Agent AI<br>
    💡 <em>Tip: For best results, analyze repositories with detailed README files</em>
</div>
""", unsafe_allow_html=True)
