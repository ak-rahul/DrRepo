"""`query_osv`: ad hoc vulnerability lookup for one exact package version."""

from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import tool

from drrepo.collectors.dependencies import build_vulnerabilities, query_osv_ids
from drrepo.collectors.manifests import normalize_pypi_name
from drrepo.config import Config
from drrepo.core.cache import DependencyLookupCache

ECOSYSTEMS = {
    "pypi": "PyPI",
    "npm": "npm",
    "go": "Go",
    "crates.io": "crates.io",
    "maven": "Maven",
    "rubygems": "RubyGems",
    "nuget": "NuGet",
    "packagist": "Packagist",
}


def lookup_package(
    package: str,
    ecosystem: str,
    version: str,
    config: Config,
    cache: DependencyLookupCache | None = None,
) -> str:
    """Human/LLM-readable OSV result for one package version (shared with the MCP server)."""
    eco = ECOSYSTEMS.get(ecosystem.strip().lower(), ecosystem.strip())
    name = normalize_pypi_name(package) if eco == "PyPI" else package.strip()
    version = version.strip().lstrip("v=")
    if not name or not version:
        return "ERROR: package and an exact version are required"
    pkg = (eco, name, version)
    try:
        with httpx.Client(
            timeout=config.collector_timeout_seconds, headers={"User-Agent": "drrepo"}
        ) as client:
            ids = query_osv_ids(client, [pkg], cache)
            vulns = build_vulnerabilities(client, ids, cache)
    except (httpx.HTTPError, ValueError) as e:
        return f"ERROR: OSV.dev lookup failed: {e}"
    if not vulns:
        return f"No known vulnerabilities for {name}@{version} ({eco})"
    return "\n".join(
        f"{v['vuln_id']} [{v.get('severity') or 'unrated'}] {v.get('summary') or ''}"
        + (f" | fixed in: {', '.join(v['fixed_versions'])}" if v.get("fixed_versions") else "")
        + f" | https://osv.dev/vulnerability/{v['vuln_id']}"
        for v in vulns
    )


def make_dependency_tools(config: Config, cache: DependencyLookupCache | None = None) -> list[Any]:
    lookup_cache = cache if config.enable_dependency_lookup_cache else None

    @tool
    def query_osv(package: str, ecosystem: str, version: str) -> str:
        """Look up known vulnerabilities (with severity and fixed versions) for one exact package version.

        Args:
            package: Package name, e.g. "requests".
            ecosystem: "PyPI", "npm", "Go", "crates.io", "Maven", "RubyGems", "NuGet", or "Packagist".
            version: Exact version, e.g. "2.25.0" (not a range).
        """
        return lookup_package(package, ecosystem, version, config, lookup_cache)

    return [query_osv]
