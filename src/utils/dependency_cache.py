"""In-memory cache for per-package OSV.dev vulnerability + deps.dev license
lookups, keyed by (ecosystem, name, version).

Injected explicitly (never a module-level global) so tests stay hermetic and
so callers control its lifetime: a fresh cache for a one-shot CLI run, or one
long-lived instance (e.g. via `st.cache_resource` in the Streamlit app) shared
across many analyses to avoid re-querying the same popular package/version
pair over and over -- the win grows with how much dependency overlap there is
across the repos being analyzed.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

PackageKey = Tuple[str, str, str]  # (ecosystem, name, version)


class DependencyLookupCache:
    """Thread-safe cache for OSV vulnerability + deps.dev license lookups."""

    def __init__(self) -> None:
        self._osv: Dict[PackageKey, List[Dict[str, Any]]] = {}
        self._license: Dict[PackageKey, Optional[str]] = {}
        self._lock = threading.Lock()

    def get_osv(self, key: PackageKey) -> Optional[List[Dict[str, Any]]]:
        """Return cached OSV findings for `key`, or None on a cache miss."""
        with self._lock:
            return self._osv.get(key)

    def set_osv(self, key: PackageKey, vulns: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._osv[key] = vulns

    def get_license(self, key: PackageKey) -> Tuple[bool, Optional[str]]:
        """Return `(was_cached, license_id)` -- `license_id` may legitimately be
        None (deps.dev couldn't determine it), so a plain `.get()` can't tell
        that apart from a cache miss; the bool does."""
        with self._lock:
            if key in self._license:
                return True, self._license[key]
            return False, None

    def set_license(self, key: PackageKey, license_id: Optional[str]) -> None:
        with self._lock:
            self._license[key] = license_id

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"osv_entries": len(self._osv), "license_entries": len(self._license)}
