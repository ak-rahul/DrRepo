"""Advanced usage examples for Publication Assistant."""
import json
from src.main import PublicationAssistant

def analyze_multiple_repos():
    """Analyze multiple repositories and compare results."""
    assistant = PublicationAssistant()
    
    repos = [
        "https://github.com/langchain-ai/langgraph",
        "https://github.com/openai/openai-python",
        "https://github.com/tiangolo/fastapi"
    ]
    
    results = []
    
    for repo_url in repos:
        print(f"\nAnalyzing: {repo_url}")
        recommendations = assistant.analyze(repo_url)
        results.append({
            "url": repo_url,
            "score": recommendations["repository"]["current_score"],
            "suggestions": len(recommendations["summary"]["total_suggestions"])
        })
    
    # Compare results
    print("\n" + "="*60)
    print("COMPARISON RESULTS")
    print("="*60)
    
    for result in sorted(results, key=lambda x: x["score"], reverse=True):
        print(f"\n{result['url']}")
        print(f"  Score: {result['score']:.1f}/100")
        print(f"  Suggestions: {result['suggestions']}")

def batch_analysis_with_filtering():
    """Analyze repos and filter by quality score."""
    assistant = PublicationAssistant()
    
    repos = [
        "https://github.com/user1/repo1",
        "https://github.com/user2/repo2",
        "https://github.com/user3/repo3"
    ]
    
    threshold = 70.0
    high_quality_repos = []
    
    for repo_url in repos:
        recommendations = assistant.analyze(repo_url)
        score = recommendations["repository"]["current_score"]
        
        if score >= threshold:
            high_quality_repos.append(repo_url)
            print(f"✓ {repo_url} - Score: {score:.1f}")
        else:
            print(f"✗ {repo_url} - Score: {score:.1f} (needs improvement)")
    
    print(f"\nHigh quality repos ({len(high_quality_repos)}/{len(repos)}):")
    for repo in high_quality_repos:
        print(f"  - {repo}")

if __name__ == "__main__":
    print("Running advanced examples...\n")
    analyze_multiple_repos()
