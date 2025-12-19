"""Fact Checker Agent - Verifies claims against actual repository content."""

from typing import Dict, List

from langchain_core.messages import HumanMessage

from src.agents.base_agent import BaseAgent
from src.tools.rag_retriever import RAGRetriever


class FactCheckerAgent(BaseAgent):
    """Agent for fact-checking README claims using RAG-powered verification.
    
    **Unique Specialization:**
    This is the ONLY agent using vector embeddings and semantic search (RAG).
    It validates that README claims are backed by actual repository evidence,
    preventing misleading or outdated documentation.
    
    **Why This Agent is Essential:**
    - Only agent performing evidence-based verification
    - Prevents documentation drift (README says X, but code doesn't do X)
    - Uses FAISS vector similarity to find proof of claims
    - Temperature 0.1 (lowest) for binary true/false precision
    
    **Distinguishing Features:**
    - Only agent using RAGRetriever tool (FAISS + HuggingFace embeddings)
    - Lowest temperature (0.1) for precise, factual verification
    - Does NOT make recommendations (only verifies existing claims)
    - Uses semantic search, not keyword matching
    
    **How RAG Works:**
    1. Indexes README content into FAISS vector store
    2. Extracts verifiable claims (features, performance, compatibility)
    3. Searches indexed content for evidence supporting each claim
    4. Returns verification status with proof snippets
    
    **Tools:**
    - RAGRetriever: FAISS vector DB with sentence-transformers embeddings
    
    **Output:**
    - fact_check_results: Verified/unverified claims with evidence
    - claims_verified: Count of successfully verified claims
    - verification_details: Evidence snippets for each claim
    
    **Dependencies:**
    - Requires repo_data (with readme_content) from RepoAnalyzer
    
    **Dependents:**
    - Synthesizer uses verification results to flag misleading documentation
    """

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
        """Execute fact checking using RAG-powered verification.

        Args:
            state: Workflow state with repo_data

        Returns:
            Updated state with fact check results

        State Updates:
            - fact_check_results: List with claim verification results
            - current_agent: Set to "FactChecker"
            - messages: Appended with fact check summary
        """
        self._log_execution("Fact-checking README claims...")

        try:
            repo_data = state["repo_data"]

            # Get readme_content from repo_data
            readme_content = repo_data.get("readme_content", "")

            # Extract verifiable claims from README
            claims = self._extract_claims(readme_content, repo_data)

            # Verify claims using RAG vector search
            verification_results = self.rag_retriever.search_for_claims(
                readme_content,
                claims
            )

            # Create fact-check prompt with verification results
            user_prompt = self._create_factcheck_prompt(
                repo_data,
                claims,
                verification_results
            )

            # Get fact-check analysis from LLM
            fact_check = self._call_llm(user_prompt)

            # Update state with fact check results
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
        """Extract verifiable claims from README for fact-checking.

        Args:
            readme_content: README text to analyze
            repo_data: Repository metadata

        Returns:
            List of claims to verify (max 5 for performance)
        """
        claims = []

        # Check for feature claims
        if "features" in readme_content.lower():
            claims.append("stated features exist")

        # Check for technology claims
        if repo_data.get("language"):
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

        return claims[:5]  # Limit to top 5 claims for performance

    def _create_factcheck_prompt(
        self,
        repo_data: Dict,
        claims: List[str],
        verification_results: List[Dict]
    ) -> str:
        """Create fact-checking prompt with RAG verification results.

        Args:
            repo_data: Repository metadata
            claims: List of claims to verify
            verification_results: RAG verification results with evidence

        Returns:
            Formatted prompt string with verification data
        """
        # Handle list of verification results
        verification_summary = "\n".join([
            f"- {result.get('claim', 'Unknown')}: {'✓ Verified' if result.get('verified', False) else '✗ Not verified'}"
            for result in verification_results
        ])

        # Safe access with defaults
        file_structure = repo_data.get('file_structure', {})

        return f"""Fact-check this repository's claims:

**Repository:** {repo_data.get('name', 'Unknown')}

**Claims to Verify:**
{chr(10).join(f'{i+1}. {claim}' for i, claim in enumerate(claims))}

**Automated Verification:**
{verification_summary}

**Repository Facts:**
- Language: {repo_data.get('language', 'Unknown')}
- Has tests: {file_structure.get('has_tests', False)}
- Has CI/CD: {file_structure.get('has_ci', False)}
- License: {repo_data.get('license', 'None')}
- Last updated: {repo_data.get('updated_at', 'Unknown')}

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
