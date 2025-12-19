"""Metadata Recommender Agent - Suggests improvements for repository metadata."""

from typing import Dict, List

from langchain_core.messages import HumanMessage

from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool


class MetadataRecommenderAgent(BaseAgent):
    """Agent for recommending metadata improvements for discoverability.
    
    **Unique Specialization:**
    This is the ONLY agent that performs competitive research by searching for
    similar successful repositories. It benchmarks your project against competitors
    to provide data-driven recommendations.
    
    **Why This Agent is Essential:**
    - Only source of external competitive intelligence in the workflow
    - Provides context-aware suggestions based on what's working in your space
    - Discovers trending topics/tags you might not know about
    
    **Distinguishing Features:**
    - Only agent using WebSearchTool for similar repository research
    - Temperature 0.4 for creative SEO/marketing suggestions
    - Focuses exclusively on discoverability (name, description, topics, SEO)
    - Does NOT analyze code or documentation content (that's ContentImprover's job)
    
    **Tools:**
    - WebSearchTool: Searches for top GitHub repositories with similar tech stack
    
    **Output:**
    - metadata_recommendations: SEO-optimized name, description, topics, keywords
    - similar_repos: Benchmark data from 3-5 successful competitors
    
    **Dependencies:**
    - Requires repo_data from RepoAnalyzer (language, current description)
    
    **Dependents:**
    - ReviewerCritic uses these recommendations in Discoverability scoring
    """

    def __init__(self):
        system_prompt = """You are a GitHub repository metadata optimization expert. Your role is to:

1. Suggest better repository names and descriptions
2. Recommend relevant topics and tags
3. Improve repository discoverability
4. Optimize for GitHub search and SEO
5. Compare with successful similar repositories

Focus on actionable recommendations that increase visibility."""
        super().__init__("MetadataRecommender", system_prompt, temperature=0.4)
        self.web_search = WebSearchTool()

    def execute(self, state: Dict) -> Dict:
        """Execute metadata recommendation analysis.

        Args:
            state: Workflow state with repo_data from RepoAnalyzer

        Returns:
            Updated state with metadata recommendations

        State Updates:
            - metadata_recommendations: List with SEO/discoverability suggestions
            - current_agent: Set to "MetadataRecommender"
            - messages: Appended with recommendations summary
        """
        self._log_execution("Analyzing metadata and discoverability...")

        try:
            repo_data = state["repo_data"]

            # Search for similar successful repositories for benchmarking
            similar_repos = self.web_search.search_similar_repositories(
                repo_data.get("language", ""),
                repo_data.get("description", "")
            )

            # Create recommendation prompt with competitive data
            user_prompt = self._create_recommendation_prompt(
                repo_data,
                similar_repos
            )

            # Get recommendations from LLM
            recommendations = self._call_llm(user_prompt)

            # Update state with metadata recommendations
            state["metadata_recommendations"].append({
                "agent": "MetadataRecommender",
                "recommendations": recommendations,
                "similar_repos": similar_repos[:3]  # Top 3 competitors
            })
            state["current_agent"] = "MetadataRecommender"
            state["messages"].append(HumanMessage(
                content=f"Metadata Recommendations:\n{recommendations}"
            ))

            self._log_execution("✓ Metadata recommendations generated")
            return state

        except Exception as e:
            self.logger.error(f"Error in MetadataRecommender: {str(e)}")
            state["errors"].append(str(e))
            return state

    def _create_recommendation_prompt(
        self,
        repo_data: Dict,
        similar_repos: List[Dict]
    ) -> str:
        """Create metadata recommendation prompt with competitive analysis.

        Args:
            repo_data: Repository metadata from RepoAnalyzer
            similar_repos: List of similar successful repositories from WebSearch

        Returns:
            Formatted prompt string with competitive benchmarks
        """
        similar_summary = "\n".join([
            f"- {repo.get('title', 'N/A')} (Topics: {', '.join(repo.get('topics', [])[:3])})"
            for repo in similar_repos[:3]
        ])

        return f"""Suggest metadata improvements for this repository:

**Current Metadata:**
- Name: {repo_data.get('name', 'Unknown')}
- Description: {repo_data.get('description', 'None')}
- Topics: {', '.join(repo_data.get('topics', [])) or 'None'}
- Language: {repo_data.get('language', 'Unknown')}
- Stars: {repo_data.get('stars', 0):,}

**Similar Successful Repositories:**
{similar_summary}

**Improvement Recommendations Needed:**
1. **Repository Name**: Is it clear and descriptive? Suggest alternatives if needed.
2. **Description**: Write a compelling 1-2 sentence description that:
   - Clearly states what the project does
   - Highlights key benefits
   - Uses relevant keywords
3. **Topics/Tags**: Suggest 5-8 relevant topics to improve discoverability:
   - Primary technology/language tags
   - Use-case tags
   - Trending relevant tags
4. **SEO Keywords**: List 5 keywords to optimize for GitHub search
5. **Tagline**: Create a memorable tagline (max 10 words)

Provide specific, actionable recommendations."""
