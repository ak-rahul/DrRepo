"""Basic usage example for DrRepo."""
from src.main import PublicationAssistant

def main():
    """Run basic analysis example."""
    # Initialize assistant
    assistant = PublicationAssistant()
    
    # Analyze a repository
    repo_url = "https://github.com/psf/requests"
    description = "Popular Python HTTP library"
    
    print(f"Analyzing {repo_url}...")
    
    # Run analysis
    results = assistant.analyze(repo_url, description)
    
    # Print summary
    print("\n=== Analysis Results ===")
    print(f"Repository: {results['repository']['name']}")
    print(f"Quality Score: {results['repository']['current_score']:.1f}/100")
    print(f"Status: {results['summary']['status']}")
    print(f"\nTop Priority Actions:")
    for i, item in enumerate(results['action_items'][:3], 1):
        print(f"{i}. [{item['priority']}] {item['action']}")
    
    # Save report
    report_path = assistant.analyze_and_save(repo_url, description)
    print(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    main()
