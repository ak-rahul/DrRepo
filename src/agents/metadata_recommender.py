"""Metadata Recommender Agent - Suggests improvements for repository metadata."""
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool


class MetadataRecommenderAgent(BaseAgent):
    """Agent for recommending metadata improvements."""
    
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
            state: Workflow state with repo_data
        
        Returns:
            Updated state with metadata recommendations
        """
        self._log_execution("Analyzing metadata and discoverability...")
        
        try:
            repo_data = state["repo_data"]
            
            # Search for similar successful repositories
            similar_repos = self.web_search.search_similar_repositories(
                repo_data.get("language", ""),
                repo_data.get("description", "")
            )
            
            # Create recommendation prompt
            user_prompt = self._create_recommendation_prompt(
                repo_data,
                similar_repos
            )
            
            # Get recommendations
            recommendations = self._call_llm(user_prompt)
            
            # Update state
            state["metadata_recommendations"].append({
                "agent": "MetadataRecommender",
                "recommendations": recommendations,
                "similar_repos": similar_repos[:3]
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
        """Create metadata recommendation prompt.
        
        Args:
            repo_data: Repository metadata
            similar_repos: List of similar successful repositories
        
        Returns:
            Formatted prompt string
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
