"""Metadata Recommender Agent - Suggests metadata improvements."""
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent
from src.tools.web_search_tool import WebSearchTool

class MetadataRecommenderAgent(BaseAgent):
    """Agent for recommending metadata and discoverability improvements."""
    
    def __init__(self):
        system_prompt = """You are a GitHub metadata optimization expert. Your role is to:
1. Suggest improved project titles and descriptions
2. Recommend relevant topics and tags for discoverability
3. Propose keywords for search optimization
4. Compare with successful similar projects
5. Advise on categorization and positioning

Focus on making the project more discoverable and appealing to the target audience."""
        
        super().__init__("MetadataRecommender", system_prompt, temperature=0.4)
        self.web_search = WebSearchTool()
    
    def execute(self, state: Dict) -> Dict:
        """Execute metadata recommendation."""
        self._log_execution("Analyzing metadata and discoverability...")
        
        try:
            repo_data = state["repo_data"]
            
            # Search for similar successful projects
            similar_repos = self.web_search.find_similar_repositories(
                repo_data["language"],
                repo_data["topics"]
            )
            
            # Create prompt
            user_prompt = self._create_recommendation_prompt(repo_data, similar_repos)
            
            # Get recommendations
            recommendations = self._call_llm(user_prompt)
            
            # Update state
            state["metadata_suggestions"].append({
                "agent": "MetadataRecommender",
                "recommendations": recommendations,
                "similar_repos": similar_repos
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
        """Create metadata recommendation prompt."""
        similar_info = "\n".join([
            f"- {repo.get('title', 'N/A')}: {repo.get('content', '')[:150]}..."
            for repo in similar_repos[:3]
        ])
        
        return f"""Provide metadata optimization recommendations for this repository:

**Current Metadata:**
- Name: {repo_data['name']}
- Description: {repo_data['description']}
- Topics: {', '.join(repo_data['topics']) if repo_data['topics'] else 'None'}
- Language: {repo_data['language']}
- Stars: {repo_data['stars']}

**Similar Successful Projects:**
{similar_info}

**Recommendations Needed:**

1. **Project Title**: Suggest a better name if current one is unclear
   - Keep it short, descriptive, and memorable
   - Include key technology/purpose if relevant

2. **Description**: Write an improved one-line description (max 150 chars)
   - Clear value proposition
   - Include target audience
   - Mention key features/benefits

3. **Topics/Tags**: Recommend 5-10 relevant topics
   - Technology stack
   - Use cases
   - Target audience
   - Problem domain

4. **Keywords**: Suggest 8-12 SEO-friendly keywords for discoverability

5. **Positioning**: How should this project be positioned in the ecosystem?

Format as clear, actionable recommendations with examples."""
