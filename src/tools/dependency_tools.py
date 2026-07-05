"""Ad hoc single-package vulnerability lookup for investigator agents.

Reuses `src.collectors.dependency_audit`'s OSV.dev client -- same query
mechanism as the bulk recon pass, just for one package the agent chooses.
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import tool

from src.collectors.dependency_audit import _query_osv
from src.config import Config


def make_dependency_tools(config: Config) -> List:
    """Build a `query_osv` tool bound to a config (for timeout settings)."""

    @tool
    def query_osv(package: str, ecosystem: str, version: str) -> str:
        """Look up known vulnerabilities for a single package/version via OSV.dev.

        Args:
            package: Package name, e.g. "requests".
            ecosystem: Package ecosystem, e.g. "PyPI", "npm", "Go", "crates.io".
            version: Exact version string to check, e.g. "2.6.0".
        """
        try:
            vulns = _query_osv([(ecosystem, package, version)], config.collector_timeout_seconds)
        except Exception as e:
            return f"ERROR: OSV.dev lookup failed: {e}"

        if not vulns:
            return f"No known vulnerabilities found for {package}@{version} ({ecosystem})"
        return "\n".join(
            f"{v['vuln_id']}: https://osv.dev/vulnerability/{v['vuln_id']}" for v in vulns
        )

    return [query_osv]
