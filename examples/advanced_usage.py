"""Advanced usage example showing custom workflow."""
from src.graph.workflow import PublicationAssistantWorkflow
from src.utils.logger import logger

def main():
    """Run advanced analysis with custom handling."""
    # Initialize workflow directly
    workflow = PublicationAssistantWorkflow()
    
    # Multiple repositories to analyze
    repositories = [
        "https://github.com/psf/requests",
        "https://github.com/django/django",
        "https://github.com/fastapi/fastapi"
    ]
    
    results = []
    
    for repo_url in repositories:
        try:
            logger.info(f"Analyzing {repo_url}...")
            
            # Execute workflow
            result = workflow.execute(repo_url, "")
            
            # Extract key metrics
            summary = result.get("final_summary", {})
            results.append({
                "repo": repo_url,
                "score": summary.get("repository", {}).get("current_score", 0),
                "status": summary.get("summary", {}).get("status", "Unknown")
            })
            
        except Exception as e:
            logger.error(f"Failed to analyze {repo_url}: {str(e)}")
            results.append({
                "repo": repo_url,
                "score": 0,
                "status": "Error"
            })
    
    # Print comparison
    print("\n=== Repository Comparison ===")
    for r in sorted(results, key=lambda x: x['score'], reverse=True):
        print(f"{r['repo']}: {r['score']:.1f}/100 ({r['status']})")


if __name__ == "__main__":
    main()
