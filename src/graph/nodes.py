"""
Node functions for LangGraph workflow.

This module contains the node functions that execute agent logic
within the LangGraph workflow. Each node corresponds to a specific
agent or processing step in the multi-agent system.
"""

from typing import Dict, List
from src.graph.state import PublicationState
from src.agents.repo_analyzer import RepoAnalyzerAgent
from src.agents.metadata_recommender import MetadataRecommenderAgent
from src.agents.content_improver import ContentImproverAgent
from src.agents.reviewer_critic import ReviewerCriticAgent
from src.agents.fact_checker import FactCheckerAgent
from src.utils.logger import logger


class WorkflowNodes:
    """Container for all workflow node functions."""
    
    def __init__(self):
        """Initialize all agents used by nodes."""
        self.repo_analyzer = RepoAnalyzerAgent()
        self.metadata_recommender = MetadataRecommenderAgent()
        self.content_improver = ContentImproverAgent()
        self.reviewer_critic = ReviewerCriticAgent()
        self.fact_checker = FactCheckerAgent()
    
    def repo_analyzer_node(self, state: PublicationState) -> PublicationState:
        """
        Repository analyzer node.
        
        Fetches and analyzes repository data, README content, and structure.
        This is the entry point of the workflow.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with repository analysis
        """
        logger.info("Executing repo_analyzer_node")
        
        try:
            updated_state = self.repo_analyzer.execute(state)
            return updated_state
        except Exception as e:
            logger.error(f"Error in repo_analyzer_node: {str(e)}")
            state["errors"].append(f"RepoAnalyzer: {str(e)}")
            state["workflow_status"] = "error"
            return state
    
    def metadata_recommender_node(self, state: PublicationState) -> PublicationState:
        """
        Metadata recommender node.
        
        Generates recommendations for repository metadata including
        title, description, topics, and keywords.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with metadata suggestions
        """
        logger.info("Executing metadata_recommender_node")
        
        try:
            updated_state = self.metadata_recommender.execute(state)
            return updated_state
        except Exception as e:
            logger.error(f"Error in metadata_recommender_node: {str(e)}")
            state["errors"].append(f"MetadataRecommender: {str(e)}")
            return state
    
    def content_improver_node(self, state: PublicationState) -> PublicationState:
        """
        Content improver node.
        
        Analyzes README content and suggests improvements for
        structure, clarity, and completeness.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with content improvement suggestions
        """
        logger.info("Executing content_improver_node")
        
        try:
            updated_state = self.content_improver.execute(state)
            return updated_state
        except Exception as e:
            logger.error(f"Error in content_improver_node: {str(e)}")
            state["errors"].append(f"ContentImprover: {str(e)}")
            return state
    
    def reviewer_critic_node(self, state: PublicationState) -> PublicationState:
        """
        Reviewer/critic node.
        
        Performs quality review and provides constructive criticism
        on documentation and repository structure.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with review feedback
        """
        logger.info("Executing reviewer_critic_node")
        
        try:
            updated_state = self.reviewer_critic.execute(state)
            return updated_state
        except Exception as e:
            logger.error(f"Error in reviewer_critic_node: {str(e)}")
            state["errors"].append(f"ReviewerCritic: {str(e)}")
            return state
    
    def fact_checker_node(self, state: PublicationState) -> PublicationState:
        """
        Fact checker node.
        
        Verifies claims made in README against actual repository
        content using RAG-based retrieval.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with fact-check results
        """
        logger.info("Executing fact_checker_node")
        
        try:
            updated_state = self.fact_checker.execute(state)
            return updated_state
        except Exception as e:
            logger.error(f"Error in fact_checker_node: {str(e)}")
            state["errors"].append(f"FactChecker: {str(e)}")
            return state
    
    def synthesizer_node(self, state: PublicationState) -> PublicationState:
        """
        Synthesizer node.
        
        Consolidates all agent outputs into final recommendations
        with prioritization and actionable insights.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with final recommendations
        """
        logger.info("Executing synthesizer_node")
        
        try:
            # Compile all recommendations
            final_recommendations = {
                "repository": {
                    "name": state["repo_data"]["name"],
                    "url": state["repo_data"]["url"],
                    "current_score": state["code_structure"].get("quality_score", 0),
                    "language": state["repo_data"]["language"],
                    "stars": state["repo_data"]["stars"],
                },
                "metadata": {
                    "suggestions": state["metadata_suggestions"],
                    "priority": "High",
                    "category": "Discoverability"
                },
                "content": {
                    "improvements": state["content_improvements"],
                    "missing_sections": state["code_structure"].get("missing_sections", []),
                    "quality_score": state["code_structure"].get("quality_score", 0),
                    "priority": "High",
                    "category": "Documentation"
                },
                "quality_review": {
                    "feedback": state["review_feedback"],
                    "checklist": self._extract_checklist(state),
                    "priority": "Medium",
                    "category": "Quality Assurance"
                },
                "fact_check": {
                    "results": state["fact_check_results"],
                    "verified_claims": len(state["fact_check_results"]),
                    "priority": "Medium",
                    "category": "Accuracy"
                },
                "summary": self._generate_summary(state),
                "action_items": self._generate_action_items(state),
                "estimated_improvement_time": self._estimate_time(state)
            }
            
            state["final_recommendations"] = final_recommendations
            state["workflow_status"] = "completed"
            
            logger.info("âœ“ Synthesis complete - workflow finished successfully")
            return state
            
        except Exception as e:
            logger.error(f"Error in synthesizer_node: {str(e)}")
            state["errors"].append(f"Synthesizer: {str(e)}")
            state["workflow_status"] = "error"
            return state
    
    def _extract_checklist(self, state: PublicationState) -> Dict:
        """Extract checklist from review feedback."""
        if state["review_feedback"]:
            return state["review_feedback"][0].get("checklist", {})
        return {}
    
    def _generate_summary(self, state: PublicationState) -> Dict:
        """Generate executive summary of analysis."""
        quality_score = state["code_structure"].get("quality_score", 0)
        
        # Determine status
        if quality_score >= 80:
            status = "Excellent"
            status_emoji = "ðŸŒŸ"
        elif quality_score >= 70:
            status = "Good"
            status_emoji = "âœ…"
        elif quality_score >= 50:
            status = "Fair"
            status_emoji = "âš ï¸"
        else:
            status = "Needs Improvement"
            status_emoji = "ðŸ”´"
        
        return {
            "overall_quality": f"{quality_score:.1f}/100",
            "status": status,
            "status_emoji": status_emoji,
            "agents_executed": 5,
            "total_suggestions": (
                len(state["metadata_suggestions"]) +
                len(state["content_improvements"]) +
                len(state["review_feedback"])
            ),
            "critical_issues": len([
                section for section in state["code_structure"].get("missing_sections", [])
                if section.lower() in ["installation", "usage", "license"]
            ]),
            "completion_percentage": self._calculate_completeness(state)
        }
    
    def _calculate_completeness(self, state: PublicationState) -> float:
        """Calculate overall repository completeness."""
        readme_analysis = state["code_structure"]
        file_structure = state["repo_data"]["file_structure"]
        
        checks = [
            # README checks (60% weight)
            readme_analysis.get("has_main_title", False),
            readme_analysis.get("has_installation", False),
            readme_analysis.get("has_usage", False),
            readme_analysis.get("has_examples", False),
            readme_analysis.get("has_code_blocks", False),
            readme_analysis.get("has_contributing", False),
            readme_analysis.get("has_license", False),
            readme_analysis.get("badge_count", 0) > 0,
            readme_analysis.get("word_count", 0) > 300,
            
            # File structure checks (40% weight)
            file_structure.get("has_tests", False),
            file_structure.get("has_requirements", False),
            file_structure.get("has_license", False),
            file_structure.get("has_ci", False),
            file_structure.get("has_contributing", False),
        ]
        
        return (sum(checks) / len(checks)) * 100
    
    def _generate_action_items(self, state: PublicationState) -> list:
        """Generate prioritized list of actionable items."""
        action_items = []
        readme_analysis = state["code_structure"]
        file_structure = state["repo_data"]["file_structure"]
        
        # High priority: Critical missing sections
        missing_critical = ["Installation", "Usage"]
        for section in readme_analysis.get("missing_sections", []):
            if section in missing_critical:
                action_items.append({
                    "priority": "ðŸ”´ High",
                    "category": "Documentation",
                    "action": f"Add '{section}' section to README",
                    "impact": "Critical for usability and adoption",
                    "effort": "Low (1-2 hours)"
                })
        
        # High priority: No code examples
        if not readme_analysis.get("has_code_blocks", False):
            action_items.append({
                "priority": "ðŸ”´ High",
                "category": "Documentation",
                "action": "Add code examples demonstrating core functionality",
                "impact": "Essential for user understanding",
                "effort": "Medium (2-4 hours)"
            })
        
        # High priority: Missing license
        if not file_structure.get("has_license", False):
            action_items.append({
                "priority": "ðŸ”´ High",
                "category": "Legal/Compliance",
                "action": "Add LICENSE file to repository",
                "impact": "Required for open source projects",
                "effort": "Low (15 minutes)"
            })
        
        # Medium priority: Badges
        if readme_analysis.get("badge_count", 0) < 3:
            action_items.append({
                "priority": "ðŸŸ¡ Medium",
                "category": "Visual/Branding",
                "action": "Add status badges (build, license, version)",
                "impact": "Improves professional appearance and trust",
                "effort": "Low (30 minutes)"
            })
        
        # Medium priority: Tests
        if not file_structure.get("has_tests", False):
            action_items.append({
                "priority": "ðŸŸ¡ Medium",
                "category": "Quality Assurance",
                "action": "Create test suite with basic test coverage",
                "impact": "Essential for production-ready code",
                "effort": "High (8+ hours)"
            })
        
        # Medium priority: CI/CD
        if not file_structure.get("has_ci", False):
            action_items.append({
                "priority": "ðŸŸ¡ Medium",
                "category": "DevOps",
                "action": "Set up CI/CD pipeline (GitHub Actions)",
                "impact": "Automates testing and quality checks",
                "effort": "Medium (2-3 hours)"
            })
        
        # Medium priority: Contributing guide
        if not file_structure.get("has_contributing", False):
            action_items.append({
                "priority": "ðŸŸ¡ Medium",
                "category": "Community",
                "action": "Add CONTRIBUTING.md file",
                "impact": "Encourages community contributions",
                "effort": "Low (1 hour)"
            })
        
        # Low priority: Images/screenshots
        if readme_analysis.get("image_count", 0) == 0:
            action_items.append({
                "priority": "ðŸŸ¢ Low",
                "category": "Visual",
                "action": "Add screenshots or demo GIF",
                "impact": "Enhances README appeal",
                "effort": "Medium (2-3 hours)"
            })
        
        # Low priority: Table of contents
        if (readme_analysis.get("section_count", 0) > 5 and 
            not readme_analysis.get("has_table_of_contents", False)):
            action_items.append({
                "priority": "ðŸŸ¢ Low",
                "category": "Navigation",
                "action": "Add table of contents to README",
                "impact": "Improves navigation in long documentation",
                "effort": "Low (20 minutes)"
            })
        
        return action_items
    
    def _estimate_time(self, state: PublicationState) -> Dict:
        """Estimate time required for improvements."""
        action_items = self._generate_action_items(state)
        
        # Parse effort estimates
        effort_mapping = {
            "Low": 1.5,      # 1-2 hours average
            "Medium": 3,     # 2-4 hours average
            "High": 10       # 8+ hours average
        }
        
        total_hours = 0
        for item in action_items:
            effort = item["effort"]
            for key, hours in effort_mapping.items():
                if key in effort:
                    total_hours += hours
                    break
        
        return {
            "total_estimated_hours": round(total_hours, 1),
            "high_priority_items": len([
                item for item in action_items 
                if "High" in item["priority"]
            ]),
            "quick_wins": len([
                item for item in action_items 
                if "Low" in item["effort"]
            ]),
            "recommendation": (
                "Start with quick wins" if total_hours < 5 
                else "Prioritize high-impact items" if total_hours < 15
                else "Plan for multiple sessions"
            )
        }


# Convenience functions for direct node usage
def create_repo_analyzer_node():
    """Factory function for repo analyzer node."""
    nodes = WorkflowNodes()
    return nodes.repo_analyzer_node


def create_metadata_recommender_node():
    """Factory function for metadata recommender node."""
    nodes = WorkflowNodes()
    return nodes.metadata_recommender_node


def create_content_improver_node():
    """Factory function for content improver node."""
    nodes = WorkflowNodes()
    return nodes.content_improver_node


def create_reviewer_critic_node():
    """Factory function for reviewer critic node."""
    nodes = WorkflowNodes()
    return nodes.reviewer_critic_node


def create_fact_checker_node():
    """Factory function for fact checker node."""
    nodes = WorkflowNodes()
    return nodes.fact_checker_node


def create_synthesizer_node():
    """Factory function for synthesizer node."""
    nodes = WorkflowNodes()
    return nodes.synthesizer_node

