"""Reviewer Critic Agent - Performs quality review and provides constructive criticism."""

from typing import Dict

from langchain_core.messages import HumanMessage

from src.agents.base_agent import BaseAgent


class ReviewerCriticAgent(BaseAgent):
    """Agent for comprehensive quality review with structured scoring.
    
    **Unique Specialization:**
    This is the ONLY agent that provides structured 100-point quality scoring
    across 4 explicit dimensions. It synthesizes insights from all previous agents
    into a cohesive quality assessment with priority rankings.
    
    **Why This Agent is Essential:**
    - Only agent providing standardized, comparable quality metrics
    - Translates 3 agents' recommendations into actionable priorities
    - Identifies "quick wins" vs "critical issues" for project planning
    - Provides objective assessment independent of any single metric
    
    **Distinguishing Features:**
    - Only agent that aggregates outputs from multiple previous agents
    - Temperature 0.3 for balanced critique (not too harsh, not too lenient)
    - Uses 4-dimension scoring framework (25 points each)
    - Provides both strategic (top 3 issues) and tactical (quick wins) guidance
    - Does NOT use any external tools (analyzes state only)
    
    **Scoring Framework:**
    1. Completeness (25 pts): Are essential sections present?
    2. Clarity (25 pts): Is it easy to understand?
    3. Professionalism (25 pts): Proper formatting and style?
    4. Discoverability (25 pts): Good SEO and topics?
    
    **Output:**
    - quality_review: Structured assessment with score breakdown
    - overall_score: 0-100 quality score
    - Top 3 critical issues and top 3 quick wins
    
    **Dependencies:**
    - Requires outputs from RepoAnalyzer, MetadataRecommender, ContentImprover
    
    **Dependents:**
    - FactChecker uses quality_review for prioritizing claim verification
    - Synthesizer uses overall_score for final status determination
    """

    def __init__(self):
        system_prompt = """You are a senior code reviewer and documentation specialist. Your role is to:

1. Perform comprehensive quality assessment
2. Identify gaps and inconsistencies
3. Evaluate against professional standards
4. Provide constructive criticism
5. Suggest priority improvements

Be honest but constructive. Focus on actionable feedback."""
        super().__init__("ReviewerCritic", system_prompt, temperature=0.3)

    def execute(self, state: Dict) -> Dict:
        """Execute quality review with structured scoring.

        Args:
            state: Workflow state with all previous analyses

        Returns:
            Updated state with quality review

        State Updates:
            - quality_review: List with structured assessment and scores
            - current_agent: Set to "ReviewerCritic"
            - messages: Appended with review summary
        """
        self._log_execution("Performing quality review...")

        try:
            repo_data = state["repo_data"]
            readme_analysis = state["code_structure"]

            # Create review prompt aggregating all previous agent outputs
            user_prompt = self._create_review_prompt(
                repo_data,
                readme_analysis,
                state.get("analysis", []),
                state.get("metadata_recommendations", []),
                state.get("content_improvements", [])
            )

            # Get comprehensive review from LLM
            review = self._call_llm(user_prompt)

            # Update state with quality review
            state["quality_review"].append({
                "agent": "ReviewerCritic",
                "review": review,
                "overall_score": readme_analysis.get("quality_score", 0)
            })
            state["current_agent"] = "ReviewerCritic"
            state["messages"].append(HumanMessage(
                content=f"Quality Review:\n{review}"
            ))

            self._log_execution("✓ Review complete")
            return state

        except Exception as e:
            self.logger.error(f"Error in ReviewerCritic: {str(e)}")
            state["errors"].append(str(e))
            return state

    def _create_review_prompt(
        self,
        repo_data: Dict,
        readme_analysis: Dict,
        analyses: list,
        metadata_recs: list,
        content_improvements: list
    ) -> str:
        """Create quality review prompt aggregating all agent insights.

        Args:
            repo_data: Repository metadata
            readme_analysis: README analysis results
            analyses: Previous agent analyses
            metadata_recs: Metadata recommendations
            content_improvements: Content improvement suggestions

        Returns:
            Formatted prompt string with comprehensive review criteria
        """
        file_structure = repo_data.get('file_structure', {})

        return f"""Perform comprehensive quality review of this repository:

**Repository Overview:**
- Name: {repo_data.get('name', 'Unknown')}
- Quality Score: {readme_analysis.get('quality_score', 0):.1f}/100
- Stars: {repo_data.get('stars', 0):,}
- Language: {repo_data.get('language', 'Unknown')}

**Documentation Status:**
- README Word Count: {readme_analysis.get('word_count', 0)}
- Sections: {readme_analysis.get('section_count', 0)}
- Code Examples: {readme_analysis.get('code_block_count', 0)}
- Missing Sections: {', '.join(readme_analysis.get('missing_sections', []))}

**Project Structure:**
- Has Tests: {file_structure.get('has_tests', False)}
- Has CI/CD: {file_structure.get('has_ci', False)}
- Has Docs: {file_structure.get('has_docs', False)}
- Has License: {bool(repo_data.get('license'))}

**Review Criteria:**
1. **Completeness** (0-25 points):
   - Essential sections present?
   - Adequate code examples?
   - Clear installation/usage instructions?

2. **Clarity** (0-25 points):
   - Easy to understand?
   - Well-organized?
   - Beginner-friendly?

3. **Professionalism** (0-25 points):
   - Proper formatting?
   - No typos/errors?
   - Consistent style?

4. **Discoverability** (0-25 points):
   - Good description?
   - Relevant topics?
   - SEO optimized?

**Provide:**
1. Score breakdown by category
2. Top 3 critical issues
3. Top 3 quick wins
4. Overall assessment (Excellent/Good/Needs Improvement/Poor)
5. Priority recommendations

Be specific and actionable."""
