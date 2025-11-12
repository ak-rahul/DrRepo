"""Repository Analyzer Agent - First agent in the workflow."""
from typing import Dict
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent
from src.tools.github_tool import GitHubTool
from src.tools.markdown_tool import MarkdownTool

class RepoAnalyzerAgent(BaseAgent):
    """Agent responsible for analyzing repository structure and content."""
    
    def __init__(self):
        system_prompt = """You are a repository analysis expert. Your role is to:
1. Examine repository structure, files, and organization
2. Analyze README content and documentation quality
3. Assess project metadata (description, topics, stars)
4. Identify the project's purpose and target audience
5. Provide a comprehensive overview of the repository's current state

Be thorough, objective, and focus on actionable insights."""
        
        super().__init__("RepoAnalyzer", system_prompt, temperature=0.2)
        self.github_tool = GitHubTool()
        self.markdown_tool = MarkdownTool()
    
    def execute(self, state: Dict) -> Dict:
        """
        Execute repository analysis.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with analysis results
        """
        self._log_execution("Starting repository analysis...")
        
        try:
            # Fetch repository data
            repo_data = self.github_tool.execute(state["repo_url"])
            
            if "error" in repo_data:
                state["errors"].append(f"GitHub fetch error: {repo_data['error']}")
                state["workflow_status"] = "error"
                return state
            
            # Analyze README structure
            readme_analysis = self.markdown_tool.execute(repo_data["readme_content"])
            
            # Prepare LLM analysis prompt
            user_prompt = self._create_analysis_prompt(
                repo_data,
                readme_analysis,
                state.get("user_description", "")
            )
            
            # Get LLM analysis
            llm_analysis = self._call_llm(user_prompt)
            
            # Update state
            state["repo_data"] = repo_data
            state["readme_content"] = repo_data["readme_content"]
            state["code_structure"] = readme_analysis
            state["current_agent"] = "RepoAnalyzer"
            
            # Add message
            state["messages"].append(HumanMessage(
                content=f"Repository Analysis Complete:\n{llm_analysis}"
            ))
            
            self._log_execution("✓ Analysis complete")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in RepoAnalyzer: {str(e)}")
            state["errors"].append(str(e))
            state["workflow_status"] = "error"
            return state
    
    def _create_analysis_prompt(
        self,
        repo_data: Dict,
        readme_analysis: Dict,
        user_description: str
    ) -> str:
        """Create comprehensive analysis prompt for LLM."""
        return f"""Analyze this GitHub repository comprehensively:

**Repository Information:**
- Name: {repo_data['name']}
- Description: {repo_data['description']}
- Language: {repo_data['language']}
- Stars: {repo_data['stars']} | Forks: {repo_data['forks']}
- Topics: {', '.join(repo_data['topics']) if repo_data['topics'] else 'None'}
- License: {repo_data.get('license', 'None')}

**File Structure:**
- Has Tests: {repo_data['file_structure']['has_tests']}
- Has Docs: {repo_data['file_structure']['has_docs']}
- Has CI/CD: {repo_data['file_structure']['has_ci']}
- Has Requirements: {repo_data['file_structure']['has_requirements']}
- Directories: {', '.join(repo_data['file_structure']['directories'][:10])}

**README Analysis:**
- Quality Score: {readme_analysis.get('quality_score', 0):.1f}/100
- Word Count: {readme_analysis['word_count']}
- Sections: {readme_analysis['section_count']}
- Has Installation: {readme_analysis['has_installation']}
- Has Usage: {readme_analysis['has_usage']}
- Has Examples: {readme_analysis['has_examples']}
- Code Blocks: {readme_analysis.get('code_block_count', 0)}
- Images: {readme_analysis.get('image_count', 0)}
- Badges: {readme_analysis.get('badge_count', 0)}
- Missing Sections: {', '.join(readme_analysis.get('missing_sections', []))}

**User Description:**
{user_description if user_description else 'Not provided'}

**Analysis Required:**
1. Project Type & Domain: What category does this project fall into?
2. Target Audience: Who is this project for?
3. Technical Stack: Main technologies used
4. Current State Assessment: Rate overall quality (1-10)
5. Strengths: What's done well?
6. Key Issues: What needs improvement?
7. Discoverability: How easy is it to find and understand this project?

Provide a concise but thorough analysis (200-300 words)."""
