"""Content Improver Agent - Suggests README content improvements."""

from typing import Dict, List

from langchain_core.messages import HumanMessage

from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool
from src.tools.markdown_tool import MarkdownTool


class ContentImproverAgent(BaseAgent):
    """Agent for improving README content and structure based on best practices.
    
    **Unique Specialization:**
    This is the ONLY agent that retrieves external documentation best practices
    from the web (e.g., "GitHub README best practices 2025"). It applies industry
    standards that you might not be aware of.
    
    **Why This Agent is Essential:**
    - Only source of external best practices knowledge in the workflow
    - Identifies missing sections based on 2025 documentation standards
    - Suggests specific visual improvements (badges, diagrams, screenshots)
    - Focuses on content/structure, NOT metadata (that's MetadataRecommender's job)
    
    **Distinguishing Features:**
    - Only agent using WebSearchTool for best practices research (NOT competitor research)
    - Uses MarkdownTool for automated improvement suggestions
    - Temperature 0.4 for creative content recommendations
    - Focuses on README structure, sections, examples, and visuals
    
    **Tools:**
    - WebSearchTool: Fetches latest README best practices
    - MarkdownTool: Generates automated improvement suggestions
    
    **Output:**
    - content_improvements: Missing sections, visual enhancements, code examples
    - markdown_suggestions: Automated structural improvements
    - quality_score: Current README quality for tracking improvements
    
    **Dependencies:**
    - Requires repo_data and code_structure from RepoAnalyzer
    
    **Dependents:**
    - ReviewerCritic uses these recommendations in Completeness/Clarity scoring
    """

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
        """Execute content improvement analysis.

        Args:
            state: Workflow state with repo_data and code_structure

        Returns:
            Updated state with content improvements

        State Updates:
            - content_improvements: List with README enhancement suggestions
            - current_agent: Set to "ContentImprover"
            - messages: Appended with improvements summary
        """
        self._log_execution("Analyzing content and suggesting improvements...")

        try:
            repo_data = state["repo_data"]
            readme_analysis = state["code_structure"]

            # Get latest README best practices from web
            best_practices = self.web_search.get_readme_best_practices()

            # Get automated markdown suggestions
            markdown_suggestions = self.markdown_tool.generate_improvement_suggestions(
                readme_analysis
            )

            # Create improvement prompt with best practices
            user_prompt = self._create_improvement_prompt(
                repo_data,
                readme_analysis,
                best_practices,
                markdown_suggestions
            )

            # Get improvements from LLM
            improvements = self._call_llm(user_prompt)

            # Update state with content improvements
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
        """Create content improvement prompt with best practices.

        Args:
            repo_data: Repository metadata
            readme_analysis: README structure analysis
            best_practices: Best practice guidelines from web search
            markdown_suggestions: Automated markdown suggestions

        Returns:
            Formatted prompt string with improvement guidelines
        """
        best_practices_summary = "\n".join([
            f"- {practice.get('title', 'N/A')}"
            for practice in best_practices[:3]
        ])

        # Get readme_content from repo_data
        readme_preview = repo_data.get('readme_content', '')[:600]

        return f"""Suggest content improvements for this README:

**Current README State:**
- Quality Score: {readme_analysis.get('quality_score', 0):.1f}/100
- Word Count: {readme_analysis.get('word_count', 0)}
- Sections: {readme_analysis.get('section_count', 0)}
- Code Examples: {readme_analysis.get('code_block_count', 0)}
- Images: {readme_analysis.get('image_count', 0)}
- Badges: {readme_analysis.get('badge_count', 0)}
- Missing: {', '.join(readme_analysis.get('missing_sections', []))}

**README Preview:**
{readme_preview}...

**Automated Suggestions:**
{chr(10).join(f"• {s.get('suggestion', '')}" for s in markdown_suggestions[:5])}

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
