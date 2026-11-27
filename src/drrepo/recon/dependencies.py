"""Dependency vulnerability + license audit via OSV.dev and deps.dev.

Reads manifests/lockfiles already in the clone (see `manifests.py`), never
installs anything. Three lookups, each bounded and cached:
1. OSV `querybatch` -> vulnerability ids per exact package version;
2. OSV `vulns/{id}` -> summary, severity, fixed versions (capped);
3. deps.dev -> declared license per package (no batch endpoint, capped).

`data` schema (status OK):
    packages_checked: int, dev_packages: int, unpinned: [name], manifests: [path],
    packages: [{ecosystem, name, version, scope: "runtime" | "dev"}],
    license_policy: {deny: [spdx], allow: [spdx]}   (from config; empty = built-in heuristic)
    vulnerabilities: [{package, ecosystem, version, dev, vuln_id, summary, severity,
                       aliases, fixed_versions, imported_in}],
    licenses: [{package, ecosystem, version, license}]

`imported_in` is the number of source files that import the package directly
(None for dev tooling or ecosystems without import detection). Zero usually
means a transitive dependency, which is still reachable through its parent, so
it informs triage and never changes a severity.
"""

from __future__ import annotations

import contextlib
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.files import iter_repo_files, read_text_file
from drrepo.recon.manifests import Package, discover, normalize_pypi_name

NAME = "dependency_audit"

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{id}"
DEPS_DEV_URL = "https://api.deps.dev/v3/systems/{system}/packages/{name}/versions/{version}"
_DEPS_DEV_SYSTEM = {"PyPI": "pypi", "npm": "npm"}

MAX_PACKAGES = 500
_OSV_BATCH_SIZE = 500  # API limit is 1000 queries per request
MAX_VULN_DETAIL_LOOKUPS = 40
MAX_LICENSE_LOOKUPS = 30


# --------------------------------------------------------------- cache ---

_MISSING = object()


class DependencyLookupCache:
    """Thread-safe in-memory cache for OSV and deps.dev lookups.

    Injected explicitly, never global: fresh per CLI run, or one long-lived
    instance owned by `AnalysisService` so a popular package looked up by one
    analysis is a free hit for the next.
    """

    def __init__(self) -> None:
        self._osv: dict[Package, list[str]] = {}
        self._vuln: dict[str, dict[str, Any]] = {}
        self._license: dict[Package, str | None] = {}
        self._lock = threading.Lock()

    def get_osv(self, key: Package) -> list[str] | None:
        """Cached vulnerability ids for `key`, or None on a miss."""
        with self._lock:
            ids = self._osv.get(key)
            return list(ids) if ids is not None else None

    def set_osv(self, key: Package, vuln_ids: list[str]) -> None:
        with self._lock:
            self._osv[key] = list(vuln_ids)

    def get_vuln(self, vuln_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._vuln.get(vuln_id)

    def set_vuln(self, vuln_id: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._vuln[vuln_id] = record

    def get_license(self, key: Package) -> tuple[bool, str | None]:
        """`(was_cached, license)`; `license` may legitimately be None (unknown),
        which a plain `.get()` couldn't distinguish from a miss."""
        with self._lock:
            value = self._license.get(key, _MISSING)
            return (False, None) if value is _MISSING else (True, value)  # type: ignore[return-value]

    def set_license(self, key: Package, license_id: str | None) -> None:
        with self._lock:
            self._license[key] = license_id

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "osv_entries": len(self._osv),
                "vuln_entries": len(self._vuln),
                "license_entries": len(self._license),
            }


# ------------------------------------------------------------- lookups ---


def query_osv_ids(
    client: httpx.Client, packages: list[Package], cache: DependencyLookupCache | None = None
) -> dict[Package, list[str]]:
    """Vulnerability ids per package. Raises httpx.HTTPError on API failure."""
    result: dict[Package, list[str]] = {}
    to_query: list[Package] = []
    for pkg in packages:
        cached = cache.get_osv(pkg) if cache else None
        if cached is not None:
            result[pkg] = cached
        else:
            to_query.append(pkg)

    for start in range(0, len(to_query), _OSV_BATCH_SIZE):
        chunk = to_query[start : start + _OSV_BATCH_SIZE]
        queries = [{"package": {"name": n, "ecosystem": e}, "version": v} for e, n, v in chunk]
        resp = client.post(OSV_BATCH_URL, json={"queries": queries})
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # One result per query, in order. A length mismatch would silently
        # pair findings with the wrong package, so fail loudly instead.
        for pkg, entry in zip(chunk, results, strict=True):
            ids = [v["id"] for v in (entry or {}).get("vulns", []) if v.get("id")]
            result[pkg] = ids
            if cache:
                cache.set_osv(pkg, ids)
    return result


def _severity_from_record(record: dict[str, Any]) -> str | None:
    db = record.get("database_specific") or {}
    raw = str(db.get("severity") or "").lower()
    return {
        "critical": "critical",
        "high": "high",
        "moderate": "medium",
        "medium": "medium",
        "low": "low",
    }.get(raw)


def _fixed_versions(record: dict[str, Any], ecosystem: str, name: str) -> list[str]:
    norm = normalize_pypi_name(name) if ecosystem == "PyPI" else name
    fixed: list[str] = []
    for affected in record.get("affected", []) or []:
        pkg = affected.get("package") or {}
        pkg_name = pkg.get("name", "")
        if pkg.get("ecosystem") != ecosystem:
            continue
        if (normalize_pypi_name(pkg_name) if ecosystem == "PyPI" else pkg_name) != norm:
            continue
        for rng in affected.get("ranges", []) or []:
            fixed.extend(ev["fixed"] for ev in rng.get("events", []) if "fixed" in ev)
    return list(dict.fromkeys(fixed))


def fetch_vuln_record(
    client: httpx.Client, vuln_id: str, cache: DependencyLookupCache | None = None
) -> dict[str, Any] | None:
    cached = cache.get_vuln(vuln_id) if cache else None
    if cached is not None:
        return cached
    try:
        resp = client.get(OSV_VULN_URL.format(id=quote(vuln_id, safe="")))
        if resp.status_code != 200:
            return None
        record: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"OSV detail lookup failed for {vuln_id}: {e}")
        return None
    if cache:
        cache.set_vuln(vuln_id, record)
    return record


def build_vulnerabilities(
    client: httpx.Client,
    ids_by_package: dict[Package, list[str]],
    cache: DependencyLookupCache | None = None,
    dev_packages: set[Package] | None = None,
) -> list[dict[str, Any]]:
    vulns: list[dict[str, Any]] = []
    detail_budget = MAX_VULN_DETAIL_LOOKUPS
    for (ecosystem, name, version), ids in ids_by_package.items():
        for vuln_id in ids:
            record = None
            if detail_budget > 0:
                record = fetch_vuln_record(client, vuln_id, cache)
                detail_budget -= 1
            vulns.append(
                {
                    "package": name,
                    "ecosystem": ecosystem,
                    "version": version,
                    "dev": (ecosystem, name, version) in (dev_packages or set()),
                    "vuln_id": vuln_id,
                    "summary": (record or {}).get("summary") or "",
                    "severity": _severity_from_record(record) if record else None,
                    "aliases": (record or {}).get("aliases") or [],
                    "fixed_versions": _fixed_versions(record, ecosystem, name) if record else [],
                }
            )
    return vulns


def query_licenses(
    client: httpx.Client, packages: list[Package], cache: DependencyLookupCache | None = None
) -> list[dict[str, Any]]:
    """Declared license per package via deps.dev. One failure -> `license: None`."""
    results: list[dict[str, Any]] = []
    for ecosystem, name, version in packages[:MAX_LICENSE_LOOKUPS]:
        pkg = (ecosystem, name, version)
        hit, license_id = cache.get_license(pkg) if cache else (False, None)
        system = _DEPS_DEV_SYSTEM.get(ecosystem)
        if not hit and system:
            url = DEPS_DEV_URL.format(
                system=system, name=quote(name, safe=""), version=quote(version, safe="")
            )
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    licenses = resp.json().get("licenses") or []
                    license_id = licenses[0] if licenses else None
            except (httpx.HTTPError, ValueError) as e:
                logger.warning(f"deps.dev license lookup failed for {name}@{version}: {e}")
            if cache:
                cache.set_license(pkg, license_id)
        results.append(
            {"package": name, "ecosystem": ecosystem, "version": version, "license": license_id}
        )
    return results


# Distributions whose import name differs from the package name.
_PYPI_IMPORT_ALIASES = {
    "pyyaml": ("yaml",),
    "beautifulsoup4": ("bs4",),
    "pillow": ("PIL",),
    "scikit-learn": ("sklearn",),
    "python-dateutil": ("dateutil",),
    "opencv-python": ("cv2",),
    "pyjwt": ("jwt",),
    "attrs": ("attr", "attrs"),
    "pymysql": ("pymysql",),
    "protobuf": ("google.protobuf",),
    "msgpack-python": ("msgpack",),
}
_PY_SUFFIXES = {".py", ".pyi"}
_JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_MAX_IMPORT_SCAN_FILES = 5000


def _import_pattern(ecosystem: str, name: str) -> re.Pattern[str] | None:
    if ecosystem == "PyPI":
        modules = _PYPI_IMPORT_ALIASES.get(name, (name.replace("-", "_"),))
        alternatives = "|".join(re.escape(m) for m in modules)
        return re.compile(rf"^\s*(?:from|import)\s+(?:{alternatives})(?=[\s.,;]|$)", re.MULTILINE)
    if ecosystem == "npm":
        quoted = re.escape(name)
        return re.compile(rf"""(?:require\(|from\s+|import\s*\(?)\s*['"]{quoted}(?:/[^'"]*)?['"]""")
    return None


def import_evidence(root: Path, packages: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """How many source files import each `(ecosystem, name)` directly. One pass over the tree."""
    patterns = {pkg: p for pkg in packages if (p := _import_pattern(*pkg)) is not None}
    counts = dict.fromkeys(patterns, 0)
    if not patterns:
        return counts
    for index, path in enumerate(iter_repo_files(root)):
        if index >= _MAX_IMPORT_SCAN_FILES:
            break
        suffix = path.suffix.lower()
        relevant = [
            (pkg, p)
            for pkg, p in patterns.items()
            if (pkg[0] == "PyPI" and suffix in _PY_SUFFIXES)
            or (pkg[0] == "npm" and suffix in _JS_SUFFIXES)
        ]
        if not relevant:
            continue
        text = read_text_file(path)
        if not text:
            continue
        for pkg, pattern in relevant:
            if pattern.search(text):
                counts[pkg] += 1
    return counts


def collect_dependency_audit(
    clone_path: str,
    config: Config,
    cache: DependencyLookupCache | None = None,
    http_client: httpx.Client | None = None,
) -> CollectorResult:
    """Audit the clone's dependencies. `http_client` is injectable for tests."""
    if not config.enable_dependency_audit:
        return CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="Disabled by config"
        )

    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="No local clone available"
        )

    deps, manifests = discover(root)
    # Runtime packages first, so caps (OSV batch, license lookups) drop dev tooling first.
    packages = sorted(deps.packages, key=lambda p: p in deps.dev)[:MAX_PACKAGES]
    runtime = [p for p in packages if p not in deps.dev]
    base = {
        "packages_checked": len(packages),
        "dev_packages": len(packages) - len(runtime),
        "unpinned": deps.unpinned,
        "manifests": manifests,
        "license_policy": {"deny": list(config.license_deny), "allow": list(config.license_allow)},
        "packages": [
            {
                "ecosystem": eco,
                "name": name,
                "version": version,
                "scope": "dev" if (eco, name, version) in deps.dev else "runtime",
            }
            for eco, name, version in packages
        ],
    }
    if not manifests:
        return CollectorResult(
            name=NAME,
            status=CollectorStatus.OK,
            data={**base, "vulnerabilities": [], "licenses": []},
            detail="No supported manifest files found",
        )

    lookup_cache = cache if config.enable_dependency_lookup_cache else None
    client_cm = (
        contextlib.nullcontext(http_client)
        if http_client is not None
        else httpx.Client(
            timeout=config.collector_timeout_seconds, headers={"User-Agent": "drrepo"}
        )
    )
    with client_cm as client:
        try:
            ids = query_osv_ids(client, packages, lookup_cache)
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"OSV.dev query failed: {e}")
            return CollectorResult(
                name=NAME, status=CollectorStatus.ERROR, detail=f"OSV.dev lookup failed: {e}"
            )
        vulnerabilities = build_vulnerabilities(client, ids, lookup_cache, deps.dev)

        licenses: list[dict[str, Any]] = []
        if config.enable_license_audit:
            try:
                licenses = query_licenses(client, runtime, lookup_cache)  # dev tools never ship
            except Exception as e:  # degraded, not failed: vuln data is still valid
                logger.warning(f"deps.dev license audit failed: {e}")

    runtime_vulnerable = sorted(
        {(v["ecosystem"], v["package"]) for v in vulnerabilities if not v.get("dev")}
    )
    evidence = import_evidence(root, runtime_vulnerable)
    for v in vulnerabilities:
        v["imported_in"] = None if v.get("dev") else evidence.get((v["ecosystem"], v["package"]))
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={**base, "vulnerabilities": vulnerabilities, "licenses": licenses},
    )
