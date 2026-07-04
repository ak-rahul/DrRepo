"""Advanced usage: analyzing and comparing multiple repositories."""

from src.config import Config
from src.graph.workflow import Workflow
from src.utils.logger import logger


def main():
    """Analyze several repositories and print a comparison."""
    config = Config.from_env()
    workflow = Workflow(config)

    repositories = [
        "https://github.com/psf/requests",
        "https://github.com/pallets/flask",
        "https://github.com/tiangolo/fastapi",
    ]

    results = []
    for repo_url in repositories:
        try:
            logger.info(f"Analyzing {repo_url}...")
            result = workflow.execute(repo_url)
            results.append(
                {
                    "repo": repo_url,
                    "score": result["overall_score"],
                    "issues": len(result["issues"]),
                }
            )
        except Exception as e:
            logger.error(f"Failed to analyze {repo_url}: {e}")
            results.append({"repo": repo_url, "score": 0, "issues": None})

    print("\n=== Repository Comparison ===")
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        print(f"{r['repo']}: {r['score']:.1f}/100 ({r['issues']} issues found)")


if __name__ == "__main__":
    main()
