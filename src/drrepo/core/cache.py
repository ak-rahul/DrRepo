"""In-memory cache for OSV.dev and deps.dev lookups.

Injected explicitly (never a module-level global) so tests stay hermetic and
callers control its lifetime: fresh per CLI run, or one long-lived instance in
the Streamlit app (`st.cache_resource`) so a popular package/version looked up
by one analysis is a free hit for the next.
"""

from __future__ import annotations

import threading
from typing import Any

PackageKey = tuple[str, str, str]  # (ecosystem, name, version)

_MISSING = object()


class DependencyLookupCache:
    """Thread-safe cache: per-package vuln ids, per-vuln details, per-package license."""

    def __init__(self) -> None:
        self._osv: dict[PackageKey, list[str]] = {}
        self._vuln: dict[str, dict[str, Any]] = {}
        self._license: dict[PackageKey, str | None] = {}
        self._lock = threading.Lock()

    def get_osv(self, key: PackageKey) -> list[str] | None:
        """Cached vulnerability ids for `key`, or None on a miss."""
        with self._lock:
            ids = self._osv.get(key)
            return list(ids) if ids is not None else None

    def set_osv(self, key: PackageKey, vuln_ids: list[str]) -> None:
        with self._lock:
            self._osv[key] = list(vuln_ids)

    def get_vuln(self, vuln_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._vuln.get(vuln_id)

    def set_vuln(self, vuln_id: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._vuln[vuln_id] = record

    def get_license(self, key: PackageKey) -> tuple[bool, str | None]:
        """`(was_cached, license)`; `license` may legitimately be None (unknown),
        which a plain `.get()` couldn't distinguish from a miss."""
        with self._lock:
            value = self._license.get(key, _MISSING)
            return (False, None) if value is _MISSING else (True, value)  # type: ignore[return-value]

    def set_license(self, key: PackageKey, license_id: str | None) -> None:
        with self._lock:
            self._license[key] = license_id

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "osv_entries": len(self._osv),
                "vuln_entries": len(self._vuln),
                "license_entries": len(self._license),
            }
