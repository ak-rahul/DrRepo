"""Dependency vulnerability audit via the OSV.dev API.

Only reads manifest files already present in the local clone (requirements.txt,
pyproject.toml, package.json) and queries OSV.dev's public batch endpoint --
no package installation of any kind, matching the "never execute untrusted
code" invariant.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from src.config import Config
from src.models import CollectorResult, CollectorStatus
from src.utils.logger import logger

_OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
_MAX_PACKAGES = 200  # keep batch requests bounded for very large monorepos

_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(==|>=|~=)\s*([A-Za-z0-9_.\-]+)")


def _parse_requirements_txt(text: str) -> List[Tuple[str, str, str]]:
    packages: List[Tuple[str, str, str]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _REQ_LINE_RE.match(line)
        if match:
            name, _, version = match.groups()
            packages.append(("PyPI", name, version))
    return packages


def _parse_pyproject_toml(text: str) -> List[Tuple[str, str, str]]:
    packages: List[Tuple[str, str, str]] = []
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return packages

    deps = data.get("project", {}).get("dependencies", [])
    for dep in deps:
        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(==|>=|~=)\s*([A-Za-z0-9_.\-]+)", dep)
        if match:
            name, _, version = match.groups()
            packages.append(("PyPI", name, version))
    return packages


def _parse_package_json(text: str) -> List[Tuple[str, str, str]]:
    packages: List[Tuple[str, str, str]] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return packages

    for section in ("dependencies", "devDependencies"):
        for name, version_range in data.get(section, {}).items():
            version = re.sub(r"^[\^~>=<\s]+", "", version_range)
            if version and version[0].isdigit():
                packages.append(("npm", name, version))
    return packages


_MANIFEST_PARSERS = {
    "requirements.txt": _parse_requirements_txt,
    "pyproject.toml": _parse_pyproject_toml,
    "package.json": _parse_package_json,
}


def _find_manifests(repo_path: Path) -> List[Tuple[str, Path]]:
    found = []
    for filename in _MANIFEST_PARSERS:
        matches = list(repo_path.rglob(filename))
        for m in matches[:3]:  # cap per-manifest-type in case of many nested packages
            found.append((filename, m))
    return found


def _query_osv(packages: List[Tuple[str, str, str]], timeout: int) -> List[Dict[str, Any]]:
    if not packages:
        return []

    queries = [
        {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
        for ecosystem, name, version in packages
    ]

    try:
        resp = httpx.post(_OSV_BATCH_URL, json={"queries": queries}, timeout=timeout)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"OSV.dev query failed: {e}")
        raise

    findings = []
    # OSV's batch API guarantees one result per query, in order; a length
    # mismatch means something is wrong with the response and results would
    # otherwise get silently paired with the wrong package.
    for (ecosystem, name, version), result in zip(packages, results, strict=True):
        vulns = result.get("vulns", [])
        for vuln in vulns:
            findings.append(
                {
                    "package": name,
                    "ecosystem": ecosystem,
                    "version": version,
                    "vuln_id": vuln.get("id"),
                }
            )
    return findings


def collect_dependency_audit(clone_path: str, config: Config) -> CollectorResult:
    """Parse dependency manifests in the clone and check them against OSV.dev."""
    if not config.enable_dependency_audit:
        return CollectorResult(
            name="dependency_audit", status=CollectorStatus.SKIPPED, detail="Disabled by config"
        )

    repo_path = Path(clone_path)
    if not repo_path.exists():
        return CollectorResult(
            name="dependency_audit",
            status=CollectorStatus.SKIPPED,
            detail="No local clone available",
        )

    manifests = _find_manifests(repo_path)
    if not manifests:
        return CollectorResult(
            name="dependency_audit",
            status=CollectorStatus.OK,
            data={"packages_checked": 0, "vulnerabilities": []},
            detail="No supported manifest files found",
        )

    all_packages: List[Tuple[str, str, str]] = []
    for filename, path in manifests:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        all_packages.extend(_MANIFEST_PARSERS[filename](text))

    all_packages = all_packages[:_MAX_PACKAGES]

    try:
        vulnerabilities = _query_osv(all_packages, config.collector_timeout_seconds)
    except Exception as e:
        return CollectorResult(
            name="dependency_audit",
            status=CollectorStatus.ERROR,
            detail=f"OSV.dev lookup failed: {e}",
        )

    return CollectorResult(
        name="dependency_audit",
        status=CollectorStatus.OK,
        data={"packages_checked": len(all_packages), "vulnerabilities": vulnerabilities},
    )
