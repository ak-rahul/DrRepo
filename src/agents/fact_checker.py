"""Fact Checker Agent - Verifies claims against actual repository content."""
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agents.base_agent import BaseAgent
from src.tools.rag_retriever import RAGRetriever

class FactCheckerAgent(BaseAgent):
    """Agent for fact-checking claims in README against actual content."""
    
    def __init__(self):
        system_prompt = """You are a fact-checking specialist. Your role is to:
1. Verify claims made in README against actual repository content
2. Identify inconsistencies or exaggerations
3. Check if stated features actually exist
4. Validate technical claims
5. Ensure accuracy of documentation

Be precise and provide evidence for your findings."""
        
        super().__init__("FactChecker", system_prompt, temperature=0.1)
        self.rag_retriever = RAGRetriever()
    
    def execute(self, state: Dict) -> Dict:
        """Execute fact checking."""
        self._log_execution("Fact-checking README claims...")
        
        try:
            repo_data = state["repo_data"]
            readme_content = state["readme_content"]
            
            # Extract claims to verify
            claims = self._extract_claims(readme_content, repo_data)
            
            # Verify claims using RAG
            verification_results = self.rag_retriever.search_for_claims(
                readme_content,
                claims
            )
            
            # Create fact-check prompt
            user_prompt = self._create_factcheck_prompt(
                repo_data,
                claims,
                verification_results
            )
            
            # Get fact-check results
            fact_check = self._call_llm(user_prompt)
            
            # Update state
            state["fact_check_results"].append({
                "agent": "FactChecker",
                "fact_check": fact_check,
                "claims_verified": len(claims),
                "verification_details": verification_results
            })
            
            state["current_agent"] = "FactChecker"
            state["messages"].append(HumanMessage(
                content=f"Fact Check Results:\n{fact_check}"
            ))
            
            self._log_execution("✓ Fact checking complete")
            return state
            
        except Exception as e:
            self.logger.error(f"Error in FactChecker: {str(e)}")
            state["errors"].append(str(e))
            return state
    
    def _extract_claims(self, readme_content: str, repo_data: Dict) -> List[str]:
        """Extract verifiable claims from README."""
        claims = []
        
        # Check for feature claims
        if "features" in readme_content.lower():
            claims.append("stated features exist")
        
        # Check for technology claims
        if repo_data["language"]:
            claims.append(f"{repo_data['language']} implementation")
        
        # Check for performance claims
        if any(word in readme_content.lower() for word in ["fast", "efficient", "optimized"]):
            claims.append("performance optimization claims")
        
        # Check for support claims
        if any(word in readme_content.lower() for word in ["supports", "compatible"]):
            claims.append("compatibility and support claims")
        
        # Check for installation claims
        if "pip install" in readme_content or "npm install" in readme_content:
            claims.append("package installation availability")
        
        return claims[:5]  # Limit to top 5 claims
    
    def _create_factcheck_prompt(
        self,
        repo_data: Dict,
        claims: List[str],
        verification_results: Dict
    ) -> str:
        """Create fact-checking prompt."""
        verification_summary = "\n".join([
            f"- {claim}: {'✓ Verified' if result['found'] else '✗ Not found'}"
            for claim, result in verification_results.items()
        ])
        
        return f"""Fact-check this repository's claims:

**Repository:** {repo_data['name']}

**Claims to Verify:**
{chr(10).join(f'{i+1}. {claim}' for i, claim in enumerate(claims))}

**Automated Verification:**
{verification_summary}

**Repository Facts:**
- Language: {repo_data['language']}
- Has tests: {repo_data['file_structure']['has_tests']}
- Has CI/CD: {repo_data['file_structure']['has_ci']}
- License: {repo_data.get('license', 'None')}
- Last updated: {repo_data['updated_at']}

**Fact-Check Analysis Required:**

1. **Accuracy Assessment**:
   - Are stated features verifiable?
   - Are technical claims supported?
   - Are there exaggerations?

2. **Inconsistencies**:
   - Conflicts between README and actual content
   - Outdated information
   - Missing implementations of stated features

3. **Verification Status**:
   - Fully verified claims
   - Partially verified claims
   - Unverified or false claims

4. **Recommendations**:
   - Claims that need evidence/proof
   - Claims that should be removed/modified
   - Missing documentation for existing features

Provide a clear, honest fact-check report."""
