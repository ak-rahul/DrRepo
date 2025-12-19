"""Check individual DrRepo components."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_tools():
    """Check if all tools are working."""
    print("🔧 Checking Tools...")
    
    # GitHub Tool
    try:
        from src.tools.github_tool import GitHubTool
        tool = GitHubTool()
        print("✅ GitHubTool initialized")
    except Exception as e:
        print(f"❌ GitHubTool: {str(e)}")
    
    # Web Search Tool
    try:
        from src.tools.web_search_tool import WebSearchTool
        tool = WebSearchTool()
        print("✅ WebSearchTool initialized")
    except Exception as e:
        print(f"❌ WebSearchTool: {str(e)}")
    
    # RAG Retriever
    try:
        from src.tools.rag_retriever import RAGRetriever
        tool = RAGRetriever()
        print("✅ RAGRetriever initialized")
    except Exception as e:
        print(f"❌ RAGRetriever: {str(e)}")
    
    # Markdown Tool
    try:
        from src.tools.markdown_tool import MarkdownTool
        tool = MarkdownTool()
        print("✅ MarkdownTool initialized")
    except Exception as e:
        print(f"❌ MarkdownTool: {str(e)}")


def check_agents():
    """Check if all agents are working."""
    print("\n🤖 Checking Agents...")
    
    agents = [
        'RepoAnalyzerAgent',
        'MetadataRecommenderAgent',
        'ContentImproverAgent',
        'ReviewerCriticAgent',
        'FactCheckerAgent'
    ]
    
    for agent_name in agents:
        try:
            if agent_name == 'RepoAnalyzerAgent':
                from src.agents.repo_analyzer import RepoAnalyzerAgent
                agent = RepoAnalyzerAgent()
            elif agent_name == 'MetadataRecommenderAgent':
                from src.agents.metadata_recommender import MetadataRecommenderAgent
                agent = MetadataRecommenderAgent()
            elif agent_name == 'ContentImproverAgent':
                from src.agents.content_improver import ContentImproverAgent
                agent = ContentImproverAgent()
            elif agent_name == 'ReviewerCriticAgent':
                from src.agents.reviewer_critic import ReviewerCriticAgent
                agent = ReviewerCriticAgent()
            elif agent_name == 'FactCheckerAgent':
                from src.agents.fact_checker import FactCheckerAgent
                agent = FactCheckerAgent()
            
            print(f"✅ {agent_name} initialized")
        except Exception as e:
            print(f"❌ {agent_name}: {str(e)}")


def check_workflow():
    """Check if workflow can be initialized."""
    print("\n🔄 Checking Workflow...")
    
    try:
        from src.main import PublicationAssistant
        assistant = PublicationAssistant()
        print("✅ PublicationAssistant initialized")
        print("✅ Workflow graph compiled")
    except Exception as e:
        print(f"❌ Workflow: {str(e)}")


def main():
    """Run all component checks."""
    print("🔍 DrRepo Component Checker\n")
    
    check_tools()
    check_agents()
    check_workflow()
    
    print("\n✅ Component check complete!")


if __name__ == "__main__":
    main()
