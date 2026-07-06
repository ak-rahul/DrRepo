"""Tests for the OSV/deps.dev per-package lookup cache."""

import threading

from src.utils.dependency_cache import DependencyLookupCache


class TestOsvCache:
    def test_miss_returns_none(self):
        cache = DependencyLookupCache()
        assert cache.get_osv(("PyPI", "requests", "2.6.0")) is None

    def test_set_then_get_hits(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "requests", "2.6.0")
        vulns = [{"package": "requests", "vuln_id": "PYSEC-2018-28"}]
        cache.set_osv(key, vulns)
        assert cache.get_osv(key) == vulns

    def test_empty_findings_list_is_a_valid_cached_value_not_a_miss(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "clean-package", "1.0.0")
        cache.set_osv(key, [])
        assert cache.get_osv(key) == []


class TestLicenseCache:
    def test_miss_reports_was_cached_false(self):
        cache = DependencyLookupCache()
        was_cached, license_id = cache.get_license(("PyPI", "requests", "2.6.0"))
        assert was_cached is False
        assert license_id is None

    def test_set_then_get_hits(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "requests", "2.6.0")
        cache.set_license(key, "Apache-2.0")
        was_cached, license_id = cache.get_license(key)
        assert was_cached is True
        assert license_id == "Apache-2.0"

    def test_none_license_is_a_valid_cached_value_distinguishable_from_a_miss(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "some-unknown-pkg", "1.0.0")
        cache.set_license(key, None)
        was_cached, license_id = cache.get_license(key)
        assert was_cached is True
        assert license_id is None


class TestStats:
    def test_reports_entry_counts(self):
        cache = DependencyLookupCache()
        cache.set_osv(("PyPI", "a", "1.0"), [])
        cache.set_osv(("PyPI", "b", "1.0"), [])
        cache.set_license(("PyPI", "a", "1.0"), "MIT")
        assert cache.stats() == {"osv_entries": 2, "license_entries": 1}


class TestThreadSafety:
    def test_concurrent_writes_to_different_keys_all_land(self):
        cache = DependencyLookupCache()

        def write_many(offset: int):
            for i in range(100):
                cache.set_osv(("PyPI", f"pkg{offset}-{i}", "1.0"), [])

        threads = [threading.Thread(target=write_many, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.stats()["osv_entries"] == 500
