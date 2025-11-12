"""Reviewer/Critic Agent - Quality checks and validation."""
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent

class ReviewerCriticAgent(BaseAgent):
    """Agent for reviewing and critiquing repository quality."""
    
    def __init__(self):
        system_prompt = """You are a strict code review and documentation quality expert. Your role is to:
1. Identify gaps in documentation and completeness
2. Check for consistency and accuracy
3. Validate structure against best practices
4. Flag missing critical sections
5. Assess professional presentation standards
6. Provide constructive criticism

Be thorough, objective, and focus on actionable improvements. Rate each aspect clearly."""
        
        super().__init__("ReviewerCritic", system_prompt, temperature=0.2)
    
    def execute(self, state: Dict) -> Dict:
        """Execute review and critique."""
        self._log_execution("Performing quality review...")
        
        try:
            repo_data = state["repo_data"]
            readme_analysis = state["code_structure"]
            file_structure = repo_data["file_structure"]
            
            # Create comprehensive review prompt
            user_prompt = self._create_review_prompt(
                repo_data,
                readme_analysis,
                file_structure
            )
            
            # Get review
            review = self._call_llm(user_prompt)
            
            # Update state
            state["review_feedback"].append({
                "agent": "ReviewerCritic",
                "review": review,
                "checklist": self._generate_checklist(readme_analysis, file_structure)
            })
            
            state["current_agent"] = "ReviewerCritic"
            state["messages"].append(HumanMessage(
                content=f"Quality Review:\n{review}"
            ))
            
            self._log_execution("âœ“ Review complete")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in ReviewerCritic: {str(e)}")
            state["errors"].append(str(e))
            return state
    
    def _create_review_prompt(
        self,
        repo_data: Dict,
        readme_analysis: Dict,
        file_structure: Dict
    ) -> str:
        """Create review prompt."""
        return f"""Perform a comprehensive quality review of this repository:

**Repository Overview:**
- Name: {repo_data['name']}
- Description: {repo_data['description']}
- Language: {repo_data['language']}
- Stars: {repo_data['stars']} | Forks: {repo_data['forks']}

**README Quality Score:** {readme_analysis.get('quality_score', 0):.1f}/100

**Completeness Checklist:**
- âœ“/âœ— README Present: {'âœ“' if readme_analysis['word_count'] > 0 else 'âœ—'}
- âœ“/âœ— Installation Guide: {'âœ“' if readme_analysis['has_installation'] else 'âœ—'}
- âœ“/âœ— Usage Instructions: {'âœ“' if readme_analysis['has_usage'] else 'âœ—'}
- âœ“/âœ— Code Examples: {'âœ“' if readme_analysis.get('has_code_blocks') else 'âœ—'}
- âœ“/âœ— Tests: {'âœ“' if file_structure['has_tests'] else 'âœ—'}
- âœ“/âœ— Contributing Guide: {'âœ“' if readme_analysis['has_contributing'] else 'âœ—'}
- âœ“/âœ— License: {'âœ“' if file_structure['has_license'] else 'âœ—'}
- âœ“/âœ— CI/CD: {'âœ“' if file_structure['has_ci'] else 'âœ—'}

**Repository Structure:**
- Has tests: {file_structure['has_tests']}
- Has docs: {file_structure['has_docs']}
- Has requirements: {file_structure['has_requirements']}
- Has Docker: {file_structure['has_docker']}
- Has Makefile: {file_structure['has_makefile']}

**Review Requirements:**

1. **Documentation Quality** (Rate 1-10):
   - Clarity and completeness
   - Professional presentation
   - Missing critical sections

2. **Repository Structure** (Rate 1-10):
   - Organization and layout
   - Missing essential files
   - Professional standards

3. **Discoverability** (Rate 1-10):
   - README appeal
   - Metadata quality
   - First impression

4. **Critical Issues** (List):
   - Must-fix problems
   - Blocking issues for professional use

5. **Recommendations Priority**:
   - High priority (must have)
   - Medium priority (should have)
   - Low priority (nice to have)

6. **Overall Assessment**:
   - Ready for production? Yes/No
   - Suitable for professional sharing? Yes/No
   - Main strengths and weaknesses

Provide honest, constructive criticism with specific examples."""
    
    def _generate_checklist(
        self,
        readme_analysis: Dict,
        file_structure: Dict
    ) -> Dict:
        """Generate a structured checklist."""
        return {
            "documentation": {
                "readme_present": readme_analysis["word_count"] > 0,
                "installation_guide": readme_analysis["has_installation"],
                "usage_instructions": readme_analysis["has_usage"],
                "examples": readme_analysis.get("has_code_blocks", False),
                "contributing_guide": readme_analysis["has_contributing"],
                "license_info": readme_analysis["has_license"],
            },
            "repository_structure": {
                "has_tests": file_structure["has_tests"],
                "has_docs": file_structure["has_docs"],
                "has_requirements": file_structure["has_requirements"],
                "has_ci_cd": file_structure["has_ci"],
                "has_license_file": file_structure["has_license"],
            },
            "quality_score": readme_analysis.get("quality_score", 0),
            "completeness_percentage": self._calculate_completeness(
                readme_analysis,
                file_structure
            )
        }
    
    def _calculate_completeness(
        self,
        readme_analysis: Dict,
        file_structure: Dict
    ) -> float:
        """Calculate overall completeness percentage."""
        checks = [
            readme_analysis["word_count"] > 100,
            readme_analysis["has_installation"],
            readme_analysis["has_usage"],
            readme_analysis.get("has_code_blocks", False),
            readme_analysis["has_contributing"],
            readme_analysis["has_license"],
            file_structure["has_tests"],
            file_structure["has_requirements"],
            file_structure["has_license"],
            file_structure["has_ci"],
        ]
        return (sum(checks) / len(checks)) * 100

