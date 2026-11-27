"""A CI quality gate with a policy more specific than `drrepo audit --fail-under`.

Fails (exit 1) when any of these hold, and always writes a SARIF file for
GitHub code scanning:

- the overall score is below --min-score;
- any category scores below --min-category;
- there is at least one critical issue, or a high-severity security issue.

    uv run python examples/policy_gate.py https://github.com/pallets/itsdangerous
    uv run python examples/policy_gate.py "$REPO_URL" --min-score 70 --sarif drrepo.sarif

The gate runs shallow (deterministic) by default, so the same commit always
gives the same verdict. Pass --deep to let LLM investigators add findings.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.log import configure_logging
from drrepo.report.exporters import to_sarif
from drrepo.service import AnalysisService


def violations(report: dict[str, Any], min_score: float, min_category: float) -> list[str]:
    found = []
    if report["overall_score"] < min_score:
        found.append(f"overall score {report['overall_score']} < {min_score}")
    for name, category in report["category_scores"].items():
        if category["assessed"] and category["score"] < min_category:
            found.append(f"{name} score {category['score']} < {min_category}")
    for issue in report["issues"]:
        blocking = issue["severity"] == "critical" or (
            issue["severity"] == "high" and issue["category"] == "security"
        )
        if blocking:
            where = f" at {issue['file']}" if issue["file"] else ""
            where += f":{issue['line']}" if issue["file"] and issue["line"] else ""
            found.append(f"{issue['severity']} {issue['category']}: {issue['title']}{where}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail CI when a repository breaks policy.")
    parser.add_argument("repo_url")
    parser.add_argument("--min-score", type=float, default=60.0)
    parser.add_argument("--min-category", type=float, default=40.0)
    parser.add_argument("--sarif", type=Path, default=Path("drrepo.sarif"))
    parser.add_argument("--deep", action="store_true", help="allow LLM deep investigations")
    args = parser.parse_args()

    config = Config.from_env()
    configure_logging(config.log_level, console_level="WARNING")
    report = AnalysisService(config).analyze(args.repo_url, deep=args.deep, record_history=False)

    args.sarif.write_text(to_sarif(report), encoding="utf-8")
    print(
        f"{report['repository']['full_name']}: {report['overall_score']}/100 (SARIF: {args.sarif})"
    )

    found = violations(report, args.min_score, args.min_category)
    for line in found:
        print(f"::error::{line}")  # rendered as an annotation by GitHub Actions
    print("Policy: FAIL" if found else "Policy: PASS")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
