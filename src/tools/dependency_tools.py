"""Ad hoc single-package vulnerability lookup for investigator agents.

Reuses `src.collectors.dependency_audit`'s OSV.dev client -- same query
mechanism as the bulk recon pass, just for one package the agent chooses.
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.tools import tool

from src.collectors.dependency_audit import _query_osv
from src.config import Config
from src.utils.dependency_cache import DependencyLookupCache


def make_dependency_tools(config: Config, cache: Optional[DependencyLookupCache] = None) -> List:
    """Build a `query_osv` tool bound to a config (for timeout settings).

    `cache`, when given, is shared with the recon `dependency_audit` collector
    so an investigator looking up a package the recon pass already checked
    gets an instant cache hit instead of a fresh OSV.dev round trip.
    """
    lookup_cache = cache if config.enable_dependency_lookup_cache else None

    @tool
    def query_osv(package: str, ecosystem: str, version: str) -> str:
        """Look up known vulnerabilities for a single package/version via OSV.dev.

        Args:
            package: Package name, e.g. "requests".
            ecosystem: Package ecosystem, e.g. "PyPI", "npm", "Go", "crates.io".
            version: Exact version string to check, e.g. "2.6.0".
        """
        try:
            vulns = _query_osv(
                [(ecosystem, package, version)], config.collector_timeout_seconds, lookup_cache
            )
        except Exception as e:
            return f"ERROR: OSV.dev lookup failed: {e}"

        if not vulns:
            return f"No known vulnerabilities found for {package}@{version} ({ecosystem})"
        return "\n".join(
            f"{v['vuln_id']}: https://osv.dev/vulnerability/{v['vuln_id']}" for v in vulns
        )

    return [query_osv]
