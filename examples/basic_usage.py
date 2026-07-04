"""Basic usage example for DrRepo v2."""

from src.config import Config
from src.graph.workflow import Workflow
from src.main import save_report


def main():
    """Run a basic analysis example."""
    config = Config.from_env()
    missing = config.validate_for_llm()
    if missing:
        raise SystemExit(f"Missing required configuration: {missing}. See .env.example.")

    workflow = Workflow(config)

    repo_url = "https://github.com/psf/requests"
    print(f"Analyzing {repo_url}...")

    result = workflow.execute(repo_url, description="Popular Python HTTP library")

    print("\n=== Analysis Results ===")
    print(f"Repository: {result['repository']['name']}")
    print(f"Overall Score: {result['overall_score']:.1f}/100")
    for name, cs in result["category_scores"].items():
        print(f"  {name}: {cs['score']:.1f}/100")

    print("\nTop Issues:")
    for issue in result["issues"][:5]:
        print(f"  [{issue['severity'].upper()}] {issue['title']}")

    report_path = save_report(result)
    print(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    main()
