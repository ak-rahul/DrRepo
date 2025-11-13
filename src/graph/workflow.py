"""LangGraph workflow for DrRepo multi-agent system."""
from typing import Dict
from langgraph.graph import StateGraph, END
from src.graph.state import State
from src.agents.repo_analyzer import RepoAnalyzerAgent
from src.agents.metadata_recommender import MetadataRecommenderAgent
from src.agents.content_improver import ContentImproverAgent
from src.agents.reviewer_critic import ReviewerCriticAgent
from src.agents.fact_checker import FactCheckerAgent
from src.utils.logger import logger


class PublicationAssistantWorkflow:
    """LangGraph workflow orchestrating all agents."""
    
    def __init__(self):
        """Initialize workflow with all agents."""
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
        """Build LangGraph workflow.
        
        Returns:
            Compiled StateGraph
        """
        # Create graph
        workflow = StateGraph(State)
        
        # Add nodes (agents)
        workflow.add_node("analyze_repo", self.repo_analyzer.execute)
        workflow.add_node("recommend_metadata", self.metadata_recommender.execute)
        workflow.add_node("improve_content", self.content_improver.execute)
        workflow.add_node("review_quality", self.reviewer_critic.execute)
        workflow.add_node("check_facts", self.fact_checker.execute)
        workflow.add_node("synthesize", self._synthesize_results)
        
        # Define workflow edges (sequential execution)
        workflow.set_entry_point("analyze_repo")
        workflow.add_edge("analyze_repo", "recommend_metadata")
        workflow.add_edge("recommend_metadata", "improve_content")
        workflow.add_edge("improve_content", "review_quality")
        workflow.add_edge("review_quality", "check_facts")
        workflow.add_edge("check_facts", "synthesize")
        workflow.add_edge("synthesize", END)
        
        # Compile
        return workflow.compile()
    
    def execute(self, repo_url: str, description: str = "") -> Dict:
        """Execute workflow for a repository.
        
        Args:
            repo_url: GitHub repository URL
            description: Optional repository description
        
        Returns:
            Final state with all results
        """
        self.logger.info(f"Starting workflow for: {repo_url}")
        
        # Initialize state
        initial_state = {
            "repo_url": repo_url,
            "description": description,
            "repo_data": {},
            "code_structure": {},
            "analysis": [],
            "metadata_recommendations": [],
            "content_improvements": [],
            "quality_review": [],
            "fact_check_results": [],
            "messages": [],
            "current_agent": "",
            "errors": [],
            "final_summary": {}  # Initialize this explicitly
        }
        
        try:
            # Execute workflow
            final_state = self.graph.invoke(initial_state)
            
            # Ensure final_summary exists
            if not final_state.get("final_summary") or not final_state["final_summary"].get("repository"):
                self.logger.warning("final_summary not properly set by synthesizer")
                final_state = self._ensure_final_summary(final_state)
            
            if final_state.get("errors"):
                self.logger.warning(f"Workflow completed with errors: {len(final_state['errors'])} error(s)")
            else:
                self.logger.info("✓ Workflow completed successfully")
            
            return final_state
            
        except Exception as e:
            self.logger.error(f"Workflow failed: {str(e)}")
            raise
    
    def _synthesize_results(self, state: Dict) -> Dict:
        """Synthesize all agent results into final recommendations.
        
        Args:
            state: Current workflow state
        
        Returns:
            Updated state with synthesized results
        """
        self.logger.info("Synthesizing final recommendations...")
        
        try:
            repo_data = state.get("repo_data", {})
            code_structure = state.get("code_structure", {})
            quality_score = code_structure.get("quality_score", 0)
            
            # Determine status
            if quality_score >= 80:
                status = "Excellent"
            elif quality_score >= 60:
                status = "Good"
            elif quality_score >= 40:
                status = "Needs Improvement"
            else:
                status = "Poor"
            
            # Count critical issues
            missing_sections = code_structure.get("missing_sections", [])
            critical_issues = len([s for s in missing_sections if s.lower() in 
                                  ['installation', 'usage', 'license']])
            
            # Extract action items from all agents
            action_items = self._extract_action_items(state)
            
            # Build final summary
            state["final_summary"] = {
                "repository": {
                    "name": repo_data.get("name", "Unknown"),
                    "url": repo_data.get("url", ""),
                    "current_score": quality_score,
                    "language": repo_data.get("language", "Unknown"),
                    "stars": repo_data.get("stars", 0),
                    "forks": repo_data.get("forks", 0)
                },
                "summary": {
                    "status": status,
                    "total_suggestions": len(action_items),
                    "critical_issues": critical_issues,
                    "quality_score": quality_score
                },
                "action_items": action_items,
                "metadata": self._summarize_metadata(state),
                "content": self._summarize_content(state),
                "quality_review": self._summarize_quality(state),
                "fact_check": self._summarize_factcheck(state)
            }
            
            self.logger.info(f"✓ Synthesized {len(action_items)} action items")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in synthesizer: {str(e)}")
            state["errors"].append(str(e))
            # Return minimal structure even on error
            state["final_summary"] = {
                "repository": {"name": "Unknown", "url": "", "current_score": 0},
                "summary": {"status": "Error", "total_suggestions": 0, "critical_issues": 0},
                "action_items": []
            }
            return state
    
    def _ensure_final_summary(self, state: Dict) -> Dict:
        """Ensure final_summary exists with fallback logic.
        
        Args:
            state: Workflow state
        
        Returns:
            State with guaranteed final_summary
        """
        repo_data = state.get("repo_data", {})
        code_structure = state.get("code_structure", {})
        quality_score = code_structure.get("quality_score", 0)
        
        if quality_score >= 80:
            status = "Excellent"
        elif quality_score >= 60:
            status = "Good"
        elif quality_score >= 40:
            status = "Needs Improvement"
        else:
            status = "Poor"
        
        action_items = self._extract_action_items(state)
        missing_sections = code_structure.get("missing_sections", [])
        critical_issues = len([s for s in missing_sections if s.lower() in ['installation', 'usage', 'license']])
        
        state["final_summary"] = {
            "repository": {
                "name": repo_data.get("name", "Unknown"),
                "url": repo_data.get("url", ""),
                "current_score": quality_score,
                "language": repo_data.get("language", "Unknown"),
                "stars": repo_data.get("stars", 0)
            },
            "summary": {
                "status": status,
                "total_suggestions": len(action_items),
                "critical_issues": critical_issues
            },
            "action_items": action_items
        }
        
        return state
    
    def _extract_action_items(self, state: Dict) -> list:
        """Extract priority action items from all analyses.
        
        Args:
            state: Workflow state
        
        Returns:
            List of action items with priority
        """
        action_items = []
        code_structure = state.get("code_structure", {})
        missing_sections = code_structure.get("missing_sections", [])
        
        # High priority: Missing critical sections
        for section in ['Installation', 'Usage', 'License']:
            if section in missing_sections:
                action_items.append({
                    "priority": "High",
                    "category": "Documentation",
                    "action": f"Add {section} section to README",
                    "impact": "Critical for usability"
                })
        
        # High priority: Code examples
        if code_structure.get("code_block_count", 0) == 0:
            action_items.append({
                "priority": "High",
                "category": "Documentation",
                "action": "Add code examples demonstrating usage",
                "impact": "Essential for understanding"
            })
        
        # Medium priority: Low word count
        if code_structure.get("word_count", 0) < 300:
            action_items.append({
                "priority": "Medium",
                "category": "Content",
                "action": "Expand README with more details",
                "impact": "Improves clarity and completeness"
            })
        
        # Medium priority: Images
        if code_structure.get("image_count", 0) == 0:
            action_items.append({
                "priority": "Medium",
                "category": "Visual",
                "action": "Add screenshots or diagrams",
                "impact": "Enhances visual appeal"
            })
        
        # Low priority: Badges
        if code_structure.get("badge_count", 0) == 0:
            action_items.append({
                "priority": "Low",
                "category": "Marketing",
                "action": "Add badges (build status, version, etc.)",
                "impact": "Improves professional appearance"
            })
        
        return action_items[:10]  # Top 10 priority items
    
    def _summarize_metadata(self, state: Dict) -> Dict:
        """Summarize metadata recommendations."""
        recs = state.get("metadata_recommendations", [])
        return {
            "suggestions": [r.get("recommendations", "") for r in recs if isinstance(r, dict)],
            "similar_repos": recs[0].get("similar_repos", []) if recs and isinstance(recs[0], dict) else []
        }
    
    def _summarize_content(self, state: Dict) -> Dict:
        """Summarize content improvements."""
        improvements = state.get("content_improvements", [])
        code_structure = state.get("code_structure", {})
        
        return {
            "missing_sections": code_structure.get("missing_sections", []),
            "improvements": [i.get("improvements", "") for i in improvements if isinstance(i, dict)],
            "quality_score": code_structure.get("quality_score", 0)
        }
    
    def _summarize_quality(self, state: Dict) -> Dict:
        """Summarize quality review."""
        reviews = state.get("quality_review", [])
        file_structure = state.get("repo_data", {}).get("file_structure", {})
        
        return {
            "checklist": {
                "has_readme": bool(state.get("repo_data", {}).get("readme_content")),
                "has_tests": file_structure.get("has_tests", False),
                "has_ci": file_structure.get("has_ci", False),
                "has_license": file_structure.get("has_license", False),
                "has_contributing": file_structure.get("has_contributing", False)
            },
            "feedback": [r.get("review", "") for r in reviews if isinstance(r, dict)]
        }
    
    def _summarize_factcheck(self, state: Dict) -> Dict:
        """Summarize fact check results."""
        fact_checks = state.get("fact_check_results", [])
        return {
            "verified": sum(fc.get("claims_verified", 0) for fc in fact_checks if isinstance(fc, dict)),
            "results": [fc.get("fact_check", "") for fc in fact_checks if isinstance(fc, dict)]
        }
