"""LangGraph workflow for multi-agent publication assistant."""
from typing import Dict, List, Literal
from langgraph.graph import StateGraph, END
from src.graph.state import PublicationState, create_initial_state
from src.agents.repo_analyzer import RepoAnalyzerAgent
from src.agents.metadata_recommender import MetadataRecommenderAgent
from src.agents.content_improver import ContentImproverAgent
from src.agents.reviewer_critic import ReviewerCriticAgent
from src.agents.fact_checker import FactCheckerAgent
from src.utils.logger import logger

class PublicationAssistantWorkflow:
    """Multi-agent workflow for repository publication assistance."""
    
    def __init__(self):
        self.logger = logger
        
        # Initialize agents
        self.repo_analyzer = RepoAnalyzerAgent()
        self.metadata_recommender = MetadataRecommenderAgent()
        self.content_improver = ContentImproverAgent()
        self.reviewer_critic = ReviewerCriticAgent()
        self.fact_checker = FactCheckerAgent()
        
        # Build workflow graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(PublicationState)
        
        # Add nodes
        workflow.add_node("repo_analyzer", self._run_repo_analyzer)
        workflow.add_node("metadata_recommender", self._run_metadata_recommender)
        workflow.add_node("content_improver", self._run_content_improver)
        workflow.add_node("reviewer_critic", self._run_reviewer_critic)
        workflow.add_node("fact_checker", self._run_fact_checker)
        workflow.add_node("synthesizer", self._synthesize_recommendations)
        
        # Set entry point
        workflow.set_entry_point("repo_analyzer")
        
        # Sequential workflow: each agent runs in order
        workflow.add_edge("repo_analyzer", "metadata_recommender")
        workflow.add_edge("metadata_recommender", "content_improver")
        workflow.add_edge("content_improver", "reviewer_critic")
        workflow.add_edge("reviewer_critic", "fact_checker")
        workflow.add_edge("fact_checker", "synthesizer")
        workflow.add_edge("synthesizer", END)
        
        return workflow.compile()
    
    def _run_repo_analyzer(self, state: PublicationState) -> PublicationState:
        """Execute repo analyzer node."""
        return self.repo_analyzer.execute(state)
    
    def _run_metadata_recommender(self, state: PublicationState) -> PublicationState:
        """Execute metadata recommender node."""
        return self.metadata_recommender.execute(state)
    
    def _run_content_improver(self, state: PublicationState) -> PublicationState:
        """Execute content improver node."""
        return self.content_improver.execute(state)
    
    def _run_reviewer_critic(self, state: PublicationState) -> PublicationState:
        """Execute reviewer critic node."""
        return self.reviewer_critic.execute(state)
    
    def _run_fact_checker(self, state: PublicationState) -> PublicationState:
        """Execute fact checker node."""
        return self.fact_checker.execute(state)
    
    def _synthesize_recommendations(self, state: PublicationState) -> PublicationState:
        """Synthesize all agent outputs into final recommendations."""
        self.logger.info("Synthesizing final recommendations...")
        
        try:
            # Compile all recommendations
            final_recommendations = {
                "repository": {
                    "name": state["repo_data"]["name"],
                    "url": state["repo_data"]["url"],
                    "current_score": state["code_structure"].get("quality_score", 0)
                },
                "metadata": {
                    "suggestions": state["metadata_suggestions"],
                    "priority": "High"
                },
                "content": {
                    "improvements": state["content_improvements"],
                    "missing_sections": state["code_structure"].get("missing_sections", []),
                    "priority": "High"
                },
                "quality_review": {
                    "feedback": state["review_feedback"],
                    "checklist": state["review_feedback"][0].get("checklist", {}) if state["review_feedback"] else {},
                    "priority": "Medium"
                },
                "fact_check": {
                    "results": state["fact_check_results"],
                    "verified": len(state["fact_check_results"]),
                    "priority": "Medium"
                },
                "summary": self._generate_summary(state),
                "action_items": self._generate_action_items(state)
            }
            
            state["final_recommendations"] = final_recommendations
            state["workflow_status"] = "completed"
            
            self.logger.info("✓ Workflow completed successfully")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in synthesizer: {str(e)}")
            state["errors"].append(str(e))
            state["workflow_status"] = "error"
            return state
    
    def _generate_summary(self, state: PublicationState) -> Dict:
        """Generate executive summary."""
        quality_score = state["code_structure"].get("quality_score", 0)
        
        return {
            "overall_quality": f"{quality_score:.1f}/100",
            "status": "Good" if quality_score >= 70 else "Needs Improvement" if quality_score >= 40 else "Poor",
            "agents_executed": 5,
            "total_suggestions": (
                len(state["metadata_suggestions"]) +
                len(state["content_improvements"]) +
                len(state["review_feedback"])
            ),
            "critical_issues": len([
                section for section in state["code_structure"].get("missing_sections", [])
                if section in ["Installation", "Usage", "License"]
            ])
        }
    
    def _generate_action_items(self, state: PublicationState) -> List[Dict]:
        """Generate prioritized action items."""
        action_items = []
        
        # High priority items
        missing_sections = state["code_structure"].get("missing_sections", [])
        for section in missing_sections:
            if section in ["Installation", "Usage"]:
                action_items.append({
                    "priority": "High",
                    "category": "Documentation",
                    "action": f"Add {section} section to README",
                    "impact": "Critical for usability"
                })
        
        # Medium priority items
        if state["code_structure"].get("badge_count", 0) < 3:
            action_items.append({
                "priority": "Medium",
                "category": "Visual",
                "action": "Add status badges (build, license, version)",
                "impact": "Improves professional appearance"
            })
        
        if not state["code_structure"].get("has_code_blocks"):
            action_items.append({
                "priority": "High",
                "category": "Documentation",
                "action": "Add code examples demonstrating usage",
                "impact": "Essential for understanding"
            })
        
        return action_items[:10]  # Top 10 action items
    
    def run(self, repo_url: str, user_description: str = "") -> Dict:
        """
        Run the complete workflow.
        
        Args:
            repo_url: GitHub repository URL
            user_description: Optional project description
            
        Returns:
            Final recommendations dictionary
        """
        self.logger.info(f"Starting workflow for: {repo_url}")
        
        # Create initial state
        initial_state = create_initial_state(repo_url, user_description)
        
        # Execute workflow
        final_state = self.graph.invoke(initial_state)
        
        if final_state["workflow_status"] == "error":
            self.logger.error(f"Workflow failed with errors: {final_state['errors']}")
        
        return final_state["final_recommendations"]
