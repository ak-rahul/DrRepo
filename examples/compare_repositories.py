"""Compare several repositories with one shared service.

Sharing one `AnalysisService` means the LLM circuit breaker and the dependency
lookup cache carry across runs (a package checked for the first repo is a free
cache hit for the next), while each run still gets its own token budget.

    uv run python examples/compare_repositories.py
"""

from __future__ import annotations

from drrepo.config import Config
from drrepo.service import AnalysisService

REPOSITORIES = [
    "https://github.com/pallets/itsdangerous",
    "https://github.com/pallets/markupsafe",
    "https://github.com/psf/requests",
]


def main() -> None:
    service = AnalysisService(Config.from_env())
    rows = []
    for url in REPOSITORIES:
        try:
            report = service.analyze(url, record_history=False)
        except Exception as e:  # keep going: one bad repo shouldn't stop the comparison
            print(f"{url}: failed ({e})")
            continue
        deep = [
            n for n, c in report["category_scores"].items() if c["investigation_depth"] == "deep"
        ]
        rows.append((report["overall_score"], url, sum(report["issue_counts"].values()), deep))

    print(f"\n{'score':>6}  {'issues':>6}  repository  (deep-dived categories)")
    for score, url, issues, deep in sorted(rows, reverse=True):
        print(f"{score:6.1f}  {issues:6d}  {url}  {', '.join(deep) or '-'}")
    if service.cache:
        print(f"\nDependency cache: {service.cache.stats()}")


if __name__ == "__main__":
    main()
