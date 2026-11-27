"""Analyze one repository from Python and print the highlights.

uv run python examples/basic_usage.py https://github.com/pallets/itsdangerous
"""

from __future__ import annotations

import sys

from drrepo.config import Config
from drrepo.log import configure_logging
from drrepo.service import AnalysisService, save_report


def main(repo_url: str) -> None:
    config = Config.from_env()
    configure_logging(config.log_level, console_level="WARNING")
    service = AnalysisService(config)

    report = service.analyze(repo_url, "Example run", progress=lambda msg: print(f"  · {msg}"))

    print(f"\n{report['repository']['full_name']}: {report['overall_score']}/100")
    for name, category in report["category_scores"].items():
        score = f"{category['score']:.0f}" if category["assessed"] else "n/a"
        print(f"  {name:<16} {score:>4}  ({category['investigation_depth']})")
    for issue in report["issues"][:5]:
        print(f"  [{issue['severity']}] {issue['title']}")

    paths = save_report(report, output_dir=__import__("pathlib").Path("reports"))
    print("\nSaved:", ", ".join(str(p) for p in paths))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "https://github.com/pallets/itsdangerous")
