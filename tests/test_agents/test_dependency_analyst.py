"""Tests for DependencyAnalyst."""

from src.agents.dependency_analyst import DependencyAnalyst, _license_category, _license_issues


class TestDependencyAnalyst:
    def test_no_manifests_found(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)

        result = agent.analyze({"dependency_audit": {"packages_checked": 0, "vulnerabilities": []}})

        assert result["score"] == 100.0
        assert result["issues"] == []
        fake_llm_client.invoke.assert_not_called()

    def test_no_vulnerabilities_found_still_scores_perfect(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)

        result = agent.analyze(
            {"dependency_audit": {"packages_checked": 10, "vulnerabilities": []}}
        )

        assert result["score"] == 100.0
        fake_llm_client.invoke.assert_not_called()

    def test_vulnerability_produces_issue_with_osv_link(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        vulns = [
            {
                "package": "requests",
                "version": "2.6.0",
                "ecosystem": "PyPI",
                "vuln_id": "PYSEC-2018-28",
            }
        ]

        result = agent.analyze(
            {"dependency_audit": {"packages_checked": 1, "vulnerabilities": vulns}}
        )

        assert len(result["issues"]) == 1
        assert "osv.dev/vulnerability/PYSEC-2018-28" in result["issues"][0]["recommendation"]
        assert result["score"] < 100.0
        fake_llm_client.invoke.assert_called_once()

    def test_strong_copyleft_dependency_flagged_in_permissive_project(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        licenses = [
            {"package": "some-gpl-lib", "ecosystem": "PyPI", "version": "1.0", "license": "GPL-3.0"}
        ]

        result = agent.analyze(
            {
                "dependency_audit": {
                    "packages_checked": 1,
                    "vulnerabilities": [],
                    "licenses": licenses,
                },
                "github_metadata": {"license_spdx_id": "MIT"},
            }
        )

        assert len(result["issues"]) == 1
        assert result["issues"][0]["source"] == "license-audit"
        assert "GPL-3.0" in result["issues"][0]["title"]
        fake_llm_client.invoke.assert_called_once()

    def test_permissive_dependency_not_flagged(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        licenses = [
            {
                "package": "requests",
                "ecosystem": "PyPI",
                "version": "2.6.0",
                "license": "Apache-2.0",
            }
        ]

        result = agent.analyze(
            {
                "dependency_audit": {
                    "packages_checked": 1,
                    "vulnerabilities": [],
                    "licenses": licenses,
                },
                "github_metadata": {"license_spdx_id": "MIT"},
            }
        )

        assert result["issues"] == []
        fake_llm_client.invoke.assert_not_called()

    def test_copyleft_dependency_not_flagged_when_repo_license_unknown(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        licenses = [
            {"package": "some-gpl-lib", "ecosystem": "PyPI", "version": "1.0", "license": "GPL-3.0"}
        ]

        result = agent.analyze(
            {
                "dependency_audit": {
                    "packages_checked": 1,
                    "vulnerabilities": [],
                    "licenses": licenses,
                },
                "github_metadata": {"license_spdx_id": None},
            }
        )

        assert result["issues"] == []

    def test_many_undeterminable_licenses_flagged_as_one_low_severity_issue(self, fake_llm_client):
        agent = DependencyAnalyst(fake_llm_client)
        licenses = [
            {"package": f"pkg{i}", "ecosystem": "PyPI", "version": "1.0", "license": None}
            for i in range(3)
        ]

        result = agent.analyze(
            {
                "dependency_audit": {
                    "packages_checked": 3,
                    "vulnerabilities": [],
                    "licenses": licenses,
                },
                "github_metadata": {"license_spdx_id": "MIT"},
            }
        )

        assert len(result["issues"]) == 1
        assert result["issues"][0]["severity"] == "low"


class TestLicenseCategory:
    def test_recognizes_permissive_licenses(self):
        assert _license_category("MIT") == "permissive"
        assert _license_category("Apache-2.0") == "permissive"

    def test_recognizes_strong_copyleft_licenses(self):
        assert _license_category("GPL-3.0") == "strong_copyleft"
        assert _license_category("AGPL-3.0-only") == "strong_copyleft"

    def test_unrecognized_or_missing_license_is_unknown(self):
        assert _license_category(None) == "unknown"
        assert _license_category("Some-Custom-License") == "unknown"

    def test_case_insensitive(self):
        assert _license_category("mit") == "permissive"


class TestLicenseIssues:
    def test_no_issues_when_repo_license_not_permissive(self):
        licenses = [{"package": "x", "ecosystem": "PyPI", "version": "1.0", "license": "GPL-3.0"}]
        assert _license_issues(licenses, "GPL-3.0") == []
        assert _license_issues(licenses, None) == []
