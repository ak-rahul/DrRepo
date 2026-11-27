"""Rank several repositories with one shared service.

Sharing one `AnalysisService` means the LLM circuit breaker and the dependency
lookup cache carry across runs (a package checked for the first repository is
a free cache hit for the next), while each run still gets its own token budget.

    uv run python examples/compare_repositories.py
    uv run python examples/compare_repositories.py https://github.com/encode/httpx \\
        https://github.com/psf/requests --shallow
"""

from __future__ import annotations

import argparse

from drrepo.config import Config
from drrepo.errors import DrRepoError
from drrepo.log import configure_logging
from drrepo.service import AnalysisService

DEFAULT_REPOSITORIES = [
    "https://github.com/pallets/itsdangerous",
    "https://github.com/pallets/markupsafe",
    "https://github.com/psf/requests",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank repositories by DrRepo score.")
    parser.add_argument("repo_urls", nargs="*", default=DEFAULT_REPOSITORIES)
    parser.add_argument("--shallow", action="store_true", help="skip deep LLM investigations")
    args = parser.parse_args()

    config = Config.from_env()
    configure_logging(config.log_level, console_level="WARNING")
    service = AnalysisService(config)

    rows = []
    for url in args.repo_urls:
        print(f"Analyzing {url} ...")
        try:
            report = service.analyze(
                url, deep=False if args.shallow else None, record_history=False
            )
        except (ValueError, DrRepoError) as e:  # bad URL or config: skip it, keep comparing
            print(f"  failed: {e}")
            continue
        scores = report["category_scores"]
        deep = [name for name, c in scores.items() if c["investigation_depth"] == "deep"]
        weakest = min(
            (c for c in scores.values() if c["assessed"]),
            key=lambda c: c["score"],
            default=None,
        )
        rows.append(
            (
                report["overall_score"],
                report["repository"]["full_name"],
                report["issue_counts"],
                weakest["category"] if weakest else "-",
                deep,
            )
        )

    print(f"\n{'score':>6}  {'crit':>4}  {'high':>4}  {'weakest':<16} repository  (deep)")
    for score, name, counts, weakest_name, deep in sorted(rows, reverse=True):
        print(
            f"{score:6.1f}  {counts['critical']:4d}  {counts['high']:4d}  "
            f"{weakest_name:<16} {name}  ({', '.join(deep) or '-'})"
        )
    if service.cache:
        print(f"\nDependency cache: {service.cache.stats()}")


if __name__ == "__main__":
    main()
