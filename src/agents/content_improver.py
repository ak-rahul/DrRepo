"""Content Improver Agent - Suggests README content improvements."""
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool
from src.tools.markdown_tool import MarkdownTool


class ContentImproverAgent(BaseAgent):
    """Agent for improving README content and structure."""
    
    def __init__(self):
        system_prompt = """You are a technical writing expert specializing in open-source documentation. Your role is to:
1. Improve README structure and organization
2. Suggest missing sections that should be added
3. Enhance clarity and readability
4. Recommend visual elements (diagrams, screenshots)
5. Propose better code examples and explanations

Focus on making the documentation clear, complete, and professional."""
        
        super().__init__("ContentImprover", system_prompt, temperature=0.4)
        self.web_search = WebSearchTool()
        self.markdown_tool = MarkdownTool()
    
    def execute(self, state: Dict) -> Dict:
        """Execute content improvement analysis."""
        self._log_execution("Analyzing content and suggesting improvements...")
        
        try:
            repo_data = state["repo_data"]
            readme_analysis = state["code_structure"]
            
            # Get best practices
            best_practices = self.web_search.get_readme_best_practices()
            
            # Get markdown suggestions
            markdown_suggestions = self.markdown_tool.generate_improvement_suggestions(
                readme_analysis
            )
            
            # Create prompt
            user_prompt = self._create_improvement_prompt(
                repo_data,
                readme_analysis,
                best_practices,
                markdown_suggestions
            )
            
            # Get improvements
            improvements = self._call_llm(user_prompt)
            
            # Update state
            state["content_improvements"].append({
                "agent": "ContentImprover",
                "improvements": improvements,
                "markdown_suggestions": markdown_suggestions,
                "quality_score": readme_analysis.get("quality_score", 0)
            })
            
            state["current_agent"] = "ContentImprover"
            state["messages"].append(HumanMessage(
                content=f"Content Improvements:\n{improvements}"
            ))
            
            self._log_execution("✓ Content improvements generated")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in ContentImprover: {str(e)}")
            state["errors"].append(str(e))
            return state
    
    def _create_improvement_prompt(
        self,
        repo_data: Dict,
        readme_analysis: Dict,
        best_practices: List[Dict],
        markdown_suggestions: List[Dict]
    ) -> str:
        """Create content improvement prompt."""
        best_practices_summary = "\n".join([
            f"- {practice.get('title', 'N/A')}"
            for practice in best_practices[:3]
        ])
        
        # Fixed: Changed state to repo_data
        readme_preview = repo_data.get('readme_content', '')[:600]
        
        return f"""Suggest content improvements for this README:

**Current README State:**
- Quality Score: {readme_analysis.get('quality_score', 0):.1f}/100
- Word Count: {readme_analysis['word_count']}
- Sections: {readme_analysis['section_count']}
- Code Examples: {readme_analysis.get('code_block_count', 0)}
- Images: {readme_analysis.get('image_count', 0)}
- Badges: {readme_analysis.get('badge_count', 0)}
- Missing: {', '.join(readme_analysis.get('missing_sections', []))}

**README Preview:**
{readme_preview}...

**Automated Suggestions:**
{chr(10).join(f"• {s['suggestion']}" for s in markdown_suggestions[:5])}

**Best Practices Reference:**
{best_practices_summary}

**Improvement Recommendations Needed:**

1. **Title & Tagline**: Suggest an improved title and compelling tagline

2. **Introduction**: Write a better opening paragraph (2-3 sentences)

3. **Missing Sections**: Prioritized list of sections to add

4. **Visual Enhancements**: Recommend badges, images, diagrams
   - Specific badge URLs
   - Types of screenshots/diagrams needed

5. **Code Examples**: Suggest better/more code examples

6. **Structure**: Recommend organizational improvements

7. **Quick Wins**: 3 easy improvements that would have high impact

Provide specific, actionable recommendations with examples where possible."""
