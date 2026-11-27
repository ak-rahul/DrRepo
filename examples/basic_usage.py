"""Analyze one repository from Python, print the highlights, and save the report.

    uv run python examples/basic_usage.py https://github.com/pallets/itsdangerous
    uv run python examples/basic_usage.py https://github.com/psf/requests --shallow --out reports

Without GROQ_API_KEY (or OPENAI_API_KEY) in `.env` the run is fully
deterministic: same scores and issues, no LLM summaries, no deep investigation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.log import configure_logging
from drrepo.service import AnalysisService, save_report


def location(issue: dict[str, Any]) -> str:
    return f"{issue['file']}:{issue['line']}" if issue["line"] else issue["file"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo_url", nargs="?", default="https://github.com/pallets/itsdangerous")
    parser.add_argument("--shallow", action="store_true", help="skip deep LLM investigations")
    parser.add_argument("--out", type=Path, default=Path("reports"), help="output directory")
    args = parser.parse_args()

    config = Config.from_env()
    configure_logging(config.log_level, console_level="WARNING")  # keep stdout readable
    service = AnalysisService(config)

    report = service.analyze(
        args.repo_url,
        deep=False if args.shallow else None,  # None = use ENABLE_DEEP_INVESTIGATION
        progress=lambda message: print(f"  · {message}"),
    )

    repo = report["repository"]
    print(f"\n{repo['full_name']}: {report['overall_score']}/100")
    for name, category in report["category_scores"].items():
        score = f"{category['score']:.0f}" if category["assessed"] else "n/a"
        print(f"  {name:<16} {score:>4}  ({category['investigation_depth']})")

    print("\nTop issues:")
    for issue in report["issues"][:5]:
        where = f" ({location(issue)})" if issue["file"] else ""
        print(f"  [{issue['severity'].upper()}] {issue['title']}{where}")

    if report["quick_wins"]:
        print("\nQuick wins:")
        for win in report["quick_wins"]:
            print(f"  - {win}")

    paths = save_report(report, output_dir=args.out)
    print("\nSaved:", ", ".join(str(p) for p in paths))


if __name__ == "__main__":
    main()
