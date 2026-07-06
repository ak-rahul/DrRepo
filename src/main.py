"""CLI entry point for DrRepo v3."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.graph.workflow import Workflow
from src.report.exporters import to_json, to_markdown, to_sarif
from src.report.history import attach_and_record_history
from src.utils.logger import logger


def print_summary(report: dict) -> None:
    """Print a short human-readable summary to the console."""
    repo = report.get("repository", {})

    print("\n" + "=" * 80)
    print("DRREPO - ANALYSIS REPORT")
    print("=" * 80 + "\n")

    print(f"Repository: {repo.get('name', 'Unknown')}")
    print(f"   URL: {repo.get('url', 'N/A')}")
    print(f"   Overall Score: {report.get('overall_score', 0):.1f}/100")

    score_history = report.get("score_history")
    if score_history:
        delta = score_history["overall_score_delta"]
        trend = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
        since = score_history["previous_timestamp"][:10]
        print(f"   Since last analysis ({since}): {delta:+.1f} ({trend})\n")
    else:
        print()

    print("Category Scores:")
    for name, cs in report.get("category_scores", {}).items():
        depth_tag = " [investigated]" if cs.get("investigation_depth") == "deep" else ""
        print(f"   {name.replace('_', ' ').title():<18} {cs['score']:.1f}/100{depth_tag}")

    deep_categories = {
        name: cs
        for name, cs in report.get("category_scores", {}).items()
        if cs.get("investigation_depth") == "deep" and cs.get("investigation_trace")
    }
    if deep_categories:
        print("\nHow it investigated:")
        for name, cs in deep_categories.items():
            print(f"   {name.replace('_', ' ').title()}:")
            for call in cs["investigation_trace"]:
                print(f"      -> {call['tool']}({call['tool_input']})")

    print("\nTop Issues:\n")
    issues = report.get("issues", [])
    if issues:
        for i, issue in enumerate(issues[:5], 1):
            location = f" ({issue['file']}:{issue['line']})" if issue.get("file") else ""
            print(f"{i}. [{issue['severity'].upper()}] {issue['title']}{location}")
            print(f"   -> {issue['recommendation']}\n")
    else:
        print("   No issues found.\n")

    print("=" * 80 + "\n")


def save_report(result: dict) -> Path:
    """Save an already-computed report result as JSON, Markdown, and SARIF in reports/."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    repo_name = result.get("repository", {}).get("name", "repository")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"{repo_name}_{timestamp}_report.json"

    json_path.write_text(to_json(result), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    sarif_path = json_path.with_suffix(".sarif")
    sarif_path.write_text(to_sarif(result), encoding="utf-8")

    logger.info(f"Reports saved to {json_path}, {md_path}, and {sarif_path}")
    return json_path


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.main <repo_url> [description]")
        print("Example: python -m src.main https://github.com/psf/requests")
        sys.exit(1)

    repo_url = sys.argv[1]
    description = sys.argv[2] if len(sys.argv) > 2 else ""

    config = Config.from_env()
    missing = config.validate_for_llm()
    if missing:
        print(f"Missing required configuration: {', '.join(missing)}")
        print("Check your .env file (see .env.example).")
        sys.exit(1)

    try:
        print(f"\nAnalyzing {repo_url}...\n")
        workflow = Workflow(config)

        result = workflow.execute(repo_url, description)
        if config.enable_score_history:
            result = attach_and_record_history(result)
        print_summary(result)

        json_path = save_report(result)
        print(f"Full report saved to: {json_path}")

    except KeyboardInterrupt:
        print("\n\nAnalysis cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        print("Check logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
