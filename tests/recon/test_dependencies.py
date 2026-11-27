import json

import httpx

from drrepo.config import Config
from drrepo.recon.dependencies import (
    DependencyLookupCache,
    build_vulnerabilities,
    collect_dependency_audit,
    query_licenses,
    query_osv_ids,
)
from tests.conftest import mock_http

VULN_RECORD = {
    "id": "GHSA-aaaa",
    "summary": "Bad thing",
    "aliases": ["CVE-2024-1"],
    "database_specific": {"severity": "MODERATE"},
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "Requests"},
            "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.31.0"}]}],
        },
        {
            "package": {"ecosystem": "PyPI", "name": "other"},
            "ranges": [{"events": [{"fixed": "9.9"}]}],
        },
    ],
}


def _batch_handler(request: httpx.Request) -> httpx.Response:
    queries = json.loads(request.content)["queries"]
    results = [
        {"vulns": [{"id": "GHSA-aaaa"}]} if q["package"]["name"] == "requests" else {}
        for q in queries
    ]
    return httpx.Response(200, json={"results": results})


def test_query_osv_ids_uses_and_fills_cache():
    cache = DependencyLookupCache()
    cache.set_osv(("PyPI", "cached", "1.0"), ["GHSA-cached"])
    seen_queries: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(len(json.loads(request.content)["queries"]))
        return _batch_handler(request)

    client = mock_http({"POST querybatch": handler})
    pkgs = [("PyPI", "requests", "2.0.0"), ("PyPI", "cached", "1.0"), ("PyPI", "clean", "1.0")]
    ids = query_osv_ids(client, pkgs, cache)
    assert ids[("PyPI", "requests", "2.0.0")] == ["GHSA-aaaa"]
    assert ids[("PyPI", "cached", "1.0")] == ["GHSA-cached"]
    assert ids[("PyPI", "clean", "1.0")] == []
    assert seen_queries == [2]  # cached package never sent
    assert cache.get_osv(("PyPI", "clean", "1.0")) == []


def test_query_osv_ids_length_mismatch_raises():
    client = mock_http({"POST querybatch": {"results": []}})
    try:
        query_osv_ids(client, [("PyPI", "a", "1")])
    except ValueError:
        return
    raise AssertionError("expected strict zip to raise")


def test_build_vulnerabilities_details_and_dev_flag():
    client = mock_http({"GET /v1/vulns/GHSA-aaaa": VULN_RECORD})
    pkg = ("PyPI", "requests", "2.0.0")
    [vuln] = build_vulnerabilities(client, {pkg: ["GHSA-aaaa"]}, dev_packages={pkg})
    assert vuln["severity"] == "medium"
    assert vuln["fixed_versions"] == ["2.31.0"]  # only for this package, name-normalized
    assert vuln["aliases"] == ["CVE-2024-1"]
    assert vuln["dev"] is True


def test_build_vulnerabilities_survives_detail_failure():
    client = mock_http({"GET /v1/vulns/": httpx.Response(500)})
    [vuln] = build_vulnerabilities(client, {("npm", "x", "1.0.0"): ["GHSA-x"]})
    assert vuln["severity"] is None and vuln["summary"] == ""


def test_query_licenses_per_package_failure_is_none():
    client = mock_http(
        {
            "GET /packages/requests/versions/2.0.0": {"licenses": ["Apache-2.0"]},
            "GET /packages/broken/": httpx.Response(500),
        }
    )
    results = query_licenses(
        client, [("PyPI", "requests", "2.0.0"), ("PyPI", "broken", "1"), ("Go", "x", "1")]
    )
    assert [r["license"] for r in results] == ["Apache-2.0", None, None]


def test_collect_end_to_end_with_mock_http(make_repo):
    root = make_repo(
        {
            "requirements.txt": "requests==2.0.0\nflask>=2\n",
            "requirements-dev.txt": "pytest==8.0.0\n",
        }
    )
    client = mock_http(
        {
            "POST querybatch": _batch_handler,
            "GET /v1/vulns/GHSA-aaaa": VULN_RECORD,
            "GET /packages/requests/": {"licenses": ["Apache-2.0"]},
        }
    )
    result = collect_dependency_audit(str(root), Config(), http_client=client)
    data = result.data
    assert result.status.value == "ok"
    assert data["packages_checked"] == 2
    assert data["dev_packages"] == 1
    assert data["unpinned"] == ["flask"]
    assert [v["package"] for v in data["vulnerabilities"]] == ["requests"]
    assert [lic["package"] for lic in data["licenses"]] == [
        "requests"
    ]  # dev deps not license-checked


def test_collect_osv_failure_is_error(make_repo):
    root = make_repo({"requirements.txt": "requests==2.0.0\n"})
    client = mock_http({"POST querybatch": httpx.Response(503)})
    result = collect_dependency_audit(str(root), Config(), http_client=client)
    assert result.status.value == "error"
    assert "OSV.dev lookup failed" in result.detail


def test_collect_no_manifests_and_disabled(make_repo):
    root = make_repo({"main.go": "package main"})
    assert (
        collect_dependency_audit(str(root), Config()).detail == "No supported manifest files found"
    )
    disabled = collect_dependency_audit(str(root), Config(enable_dependency_audit=False))
    assert disabled.status.value == "skipped"


class TestCache:
    def test_osv_roundtrip_and_copy_semantics(self):
        cache = DependencyLookupCache()
        key = ("PyPI", "requests", "2.0.0")
        assert cache.get_osv(key) is None
        cache.set_osv(key, ["GHSA-1"])
        got = cache.get_osv(key)
        assert got == ["GHSA-1"]
        got.append("mutated")
        assert cache.get_osv(key) == ["GHSA-1"]

    def test_license_distinguishes_none_from_miss(self):
        cache = DependencyLookupCache()
        key = ("npm", "left-pad", "1.0.0")
        assert cache.get_license(key) == (False, None)
        cache.set_license(key, None)
        assert cache.get_license(key) == (True, None)

    def test_stats(self):
        cache = DependencyLookupCache()
        cache.set_vuln("GHSA-1", {"id": "GHSA-1"})
        assert cache.stats() == {"osv_entries": 0, "vuln_entries": 1, "license_entries": 0}
