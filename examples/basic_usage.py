"""Basic usage example for Publication Assistant."""
from src.main import PublicationAssistant

def main():
    # Initialize assistant
    assistant = PublicationAssistant()
    
    # Analyze a repository
    repo_url = "https://github.com/yourusername/your-repo"
    
    print(f"Analyzing {repo_url}...\n")
    
    recommendations = assistant.analyze(
        repo_url=repo_url,
        user_description="A Python tool for analyzing GitHub repositories"
    )
    
    # Print summary
    assistant.print_summary(recommendations)
    
    # Export detailed report
    assistant.export_report(recommendations, "my_repo_analysis.json")
    
    # Access specific recommendations
    print("\n📋 Metadata Suggestions:")
    for suggestion in recommendations["metadata"]["suggestions"]:
        print(f"- {suggestion}")
    
    print("\n✍️ Content Improvements:")
    for improvement in recommendations["content"]["improvements"]:
        print(f"- {improvement}")

if __name__ == "__main__":
    main()
