"""Verify all DrRepo imports work correctly."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify_imports():
    """Verify all module imports."""
    print("📦 Verifying Imports...\n")
    
    imports = [
        # Utils
        ("src.utils.config", "config"),
        ("src.utils.logger", "logger"),
        ("src.utils.retry", "retry_with_backoff"),
        ("src.utils.health_check", "HealthChecker"),
        ("src.utils.exceptions", "DrRepoException"),
        ("src.utils.circuit_breaker", "CircuitBreaker"),
        
        # Tools
        ("src.tools.github_tool", "GitHubTool"),
        ("src.tools.web_search_tool", "WebSearchTool"),
        ("src.tools.rag_retriever", "RAGRetriever"),
        ("src.tools.markdown_tool", "MarkdownTool"),
        
        # Agents
        ("src.agents.base_agent", "BaseAgent"),
        ("src.agents.repo_analyzer", "RepoAnalyzerAgent"),
        ("src.agents.metadata_recommender", "MetadataRecommenderAgent"),
        ("src.agents.content_improver", "ContentImproverAgent"),
        ("src.agents.reviewer_critic", "ReviewerCriticAgent"),
        ("src.agents.fact_checker", "FactCheckerAgent"),
        
        # Main
        ("src.main", "PublicationAssistant"),
    ]
    
    failed = []
    
    for module, name in imports:
        try:
            exec(f"from {module} import {name}")
            print(f"✅ {module}.{name}")
        except Exception as e:
            print(f"❌ {module}.{name}: {str(e)[:50]}")
            failed.append((module, name, str(e)))
    
    if failed:
        print(f"\n❌ {len(failed)} import(s) failed:")
        for module, name, error in failed:
            print(f"   - {module}.{name}: {error[:50]}")
        return 1
    else:
        print(f"\n✅ All {len(imports)} imports successful!")
        return 0


if __name__ == "__main__":
    sys.exit(verify_imports())
