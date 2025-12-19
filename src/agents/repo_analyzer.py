"""Repository Analyzer Agent - Analyzes GitHub repository structure and metadata."""

from typing import Dict

from langchain_core.messages import HumanMessage

from src.agents.base_agent import BaseAgent
from src.tools.github_tool import GitHubTool
from src.tools.markdown_tool import MarkdownTool


class RepoAnalyzerAgent(BaseAgent):
    """Agent for analyzing repository structure and extracting factual metadata.
    
    **Unique Specialization:**
    This is the ONLY agent with direct GitHub API access. It serves as the data
    foundation for all downstream agents by extracting objective, factual information
    from the repository.
    
    **Why This Agent is Essential:**
    - Without RepoAnalyzer, no other agent has data to analyze
    - Provides quality_score baseline used throughout workflow
    - Extracts file structure (tests, CI/CD, docs) that other agents reference
    
    **Distinguishing Features:**
    - Lowest temperature (0.2) for consistent, factual analysis
    - Only agent using GitHubTool (PyGithub wrapper)
    - Only agent using MarkdownTool for structural README parsing
    - First agent in sequential workflow (no dependencies)
    
    **Tools:**
    - GitHubTool: Fetches repo metadata (stars, forks, topics, license, etc.)
    - MarkdownTool: Analyzes README structure (sections, code blocks, quality score)
    
    **Output:**
    - repo_data: Complete repository metadata dictionary
    - code_structure: README analysis with quality_score (0-100)
    - analysis: Factual assessment of repo health and maturity
    
    **Dependents:**
    All 4 downstream agents rely on repo_data and code_structure populated by this agent.
    """

    def __init__(self):
        system_prompt = """You are a GitHub repository analysis expert. Your role is to:

1. Analyze repository structure and organization
2. Extract key metadata (stars, forks, language, topics)
3. Evaluate README quality and completeness
4. Identify project type and category
5. Assess overall repository health

Focus on factual analysis and comprehensive data extraction."""
        super().__init__("RepoAnalyzer", system_prompt, temperature=0.2)
        self.github_tool = GitHubTool()
        self.markdown_tool = MarkdownTool()

    def execute(self, state: Dict) -> Dict:
        """Execute repository analysis.

        Args:
            state: Workflow state containing repo_url

        Returns:
            Updated state with repo_data and code_structure

        State Updates:
            - repo_data: GitHub metadata (stars, language, topics, file_structure)
            - code_structure: README metrics (quality_score, sections, word_count)
            - analysis: List with factual repo health assessment
            - current_agent: Set to "RepoAnalyzer"
            - messages: Appended with analysis summary
        """
        self._log_execution("Starting repository analysis...")

        try:
            repo_url = state["repo_url"]

            # Fetch repository data from GitHub API
            repo_data = self.github_tool.execute(repo_url)

            # Analyze README structure and quality
            readme_analysis = self.markdown_tool.execute(
                repo_data.get("readme_content", "")
            )

            # Create analysis prompt with factual data
            user_prompt = self._create_analysis_prompt(repo_data, readme_analysis)

            # Get LLM analysis
            analysis = self._call_llm(user_prompt)

            # Update state with factual data and analysis
            state["repo_data"] = repo_data
            state["code_structure"] = readme_analysis
            state["analysis"].append({
                "agent": "RepoAnalyzer",
                "analysis": analysis,
                "metadata": {
                    "stars": repo_data.get("stars", 0),
                    "forks": repo_data.get("forks", 0),
                    "language": repo_data.get("language", "Unknown"),
                    "quality_score": readme_analysis.get("quality_score", 0)
                }
            })
            state["current_agent"] = "RepoAnalyzer"
            state["messages"].append(HumanMessage(
                content=f"Repository Analysis:\n{analysis}"
            ))

            self._log_execution("✓ Analysis complete")
            return state

        except Exception as e:
            self.logger.error(f"Error in RepoAnalyzer: {str(e)}")
            state["errors"].append(str(e))
            return state

    def _create_analysis_prompt(
        self,
        repo_data: Dict,
        readme_analysis: Dict
    ) -> str:
        """Create repository analysis prompt.

        Args:
            repo_data: Repository metadata from GitHub API
            readme_analysis: README structure analysis from MarkdownTool

        Returns:
            Formatted prompt string with factual data
        """
        return f"""Analyze this GitHub repository:

**Repository Information:**
- Name: {repo_data.get('name', 'Unknown')}
- Description: {repo_data.get('description', 'None')}
- Language: {repo_data.get('language', 'Unknown')}
- Stars: {repo_data.get('stars', 0):,}
- Forks: {repo_data.get('forks', 0):,}
- Topics: {', '.join(repo_data.get('topics', [])) or 'None'}
- License: {repo_data.get('license', 'None')}
- Last Updated: {repo_data.get('updated_at', 'Unknown')}

**README Analysis:**
- Quality Score: {readme_analysis.get('quality_score', 0):.1f}/100
- Word Count: {readme_analysis.get('word_count', 0)}
- Sections: {readme_analysis.get('section_count', 0)}
- Code Examples: {readme_analysis.get('code_block_count', 0)}
- Images: {readme_analysis.get('image_count', 0)}

**File Structure:**
- Has Tests: {repo_data.get('file_structure', {}).get('has_tests', False)}
- Has CI/CD: {repo_data.get('file_structure', {}).get('has_ci', False)}
- Has Documentation: {repo_data.get('file_structure', {}).get('has_docs', False)}

Provide a comprehensive analysis covering:
1. **Repository Health**: Overall assessment of repository quality
2. **Documentation Quality**: README completeness and clarity
3. **Project Maturity**: Development stage and maintenance status
4. **Key Strengths**: What this repository does well
5. **Improvement Areas**: Main areas needing attention

Keep analysis factual and actionable."""
