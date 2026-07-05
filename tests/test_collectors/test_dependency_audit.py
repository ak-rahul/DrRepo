"""Tests for the dependency audit collector (manifest parsing + OSV.dev + deps.dev)."""

from unittest.mock import MagicMock, Mock, patch

from src.collectors.dependency_audit import (
    _parse_package_json,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    _query_licenses,
    collect_dependency_audit,
)
from src.models import CollectorStatus


class TestManifestParsers:
    def test_parses_requirements_txt(self):
        text = "requests==2.6.0\nflask>=1.0\n# a comment\n\nnumpy~=1.20\n"
        packages = _parse_requirements_txt(text)

        assert ("PyPI", "requests", "2.6.0") in packages
        assert ("PyPI", "flask", "1.0") in packages
        assert ("PyPI", "numpy", "1.20") in packages

    def test_parses_pyproject_toml(self):
        text = '[project]\ndependencies = ["requests==2.6.0", "click>=8.0"]\n'
        packages = _parse_pyproject_toml(text)

        assert ("PyPI", "requests", "2.6.0") in packages

    def test_parses_package_json(self):
        text = '{"dependencies": {"lodash": "^4.17.20"}, "devDependencies": {"jest": "~29.0.0"}}'
        packages = _parse_package_json(text)

        assert ("npm", "lodash", "4.17.20") in packages
        assert ("npm", "jest", "29.0.0") in packages

    def test_malformed_package_json_returns_empty(self):
        assert _parse_package_json("{not valid json") == []


class TestCollectDependencyAudit:
    def test_no_manifests_found(self, fake_config, tmp_path):
        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.OK
        assert result.data["packages_checked"] == 0

    def test_disabled_by_config(self, fake_config, tmp_path):
        fake_config.enable_dependency_audit = False

        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.SKIPPED

    @patch("src.collectors.dependency_audit.httpx.post")
    def test_finds_vulnerable_package(self, mock_post, fake_config, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [{"vulns": [{"id": "PYSEC-2018-28"}, {"id": "PYSEC-2023-74"}]}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.OK
        assert result.data["packages_checked"] == 1
        vuln_ids = {v["vuln_id"] for v in result.data["vulnerabilities"]}
        assert "PYSEC-2018-28" in vuln_ids

    @patch("src.collectors.dependency_audit.httpx.post")
    def test_osv_failure_returns_error_status(self, mock_post, fake_config, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")
        mock_post.side_effect = ConnectionError("network down")

        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.ERROR

    @patch("src.collectors.dependency_audit.httpx.Client")
    @patch("src.collectors.dependency_audit.httpx.post")
    def test_populates_licenses_alongside_vulnerabilities(
        self, mock_post, mock_client_cls, fake_config, tmp_path
    ):
        (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")

        mock_osv_response = Mock()
        mock_osv_response.json.return_value = {"results": [{"vulns": []}]}
        mock_osv_response.raise_for_status = Mock()
        mock_post.return_value = mock_osv_response

        mock_license_response = Mock()
        mock_license_response.status_code = 200
        mock_license_response.json.return_value = {"licenses": ["Apache-2.0"]}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_license_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.OK
        assert result.data["licenses"] == [
            {
                "package": "requests",
                "ecosystem": "PyPI",
                "version": "2.6.0",
                "license": "Apache-2.0",
            }
        ]

    @patch("src.collectors.dependency_audit.httpx.Client")
    @patch("src.collectors.dependency_audit.httpx.post")
    def test_license_audit_disabled_by_config_yields_empty_list(
        self, mock_post, mock_client_cls, fake_config, tmp_path
    ):
        (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")
        fake_config.enable_license_audit = False

        mock_osv_response = Mock()
        mock_osv_response.json.return_value = {"results": [{"vulns": []}]}
        mock_osv_response.raise_for_status = Mock()
        mock_post.return_value = mock_osv_response

        result = collect_dependency_audit(str(tmp_path), fake_config)

        assert result.data["licenses"] == []
        mock_client_cls.assert_not_called()


class TestQueryLicenses:
    def test_returns_first_license_for_known_package(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"licenses": ["MIT"]}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("src.collectors.dependency_audit.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = _query_licenses([("PyPI", "requests", "2.6.0")], timeout=10)

        assert result == [
            {"package": "requests", "ecosystem": "PyPI", "version": "2.6.0", "license": "MIT"}
        ]

    def test_unsupported_ecosystem_yields_none_license_without_network_call(self):
        mock_client = MagicMock()

        with patch("src.collectors.dependency_audit.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = _query_licenses([("cargo", "serde", "1.0.0")], timeout=10)

        assert result == [
            {"package": "serde", "ecosystem": "cargo", "version": "1.0.0", "license": None}
        ]
        mock_client.get.assert_not_called()

    def test_package_not_found_yields_none_license(self):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("src.collectors.dependency_audit.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = _query_licenses([("PyPI", "some-nonexistent-pkg", "1.0.0")], timeout=10)

        assert result[0]["license"] is None

    def test_network_failure_on_one_package_does_not_raise(self):
        import httpx as httpx_module

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx_module.ConnectError("network down")

        with patch("src.collectors.dependency_audit.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = _query_licenses([("PyPI", "requests", "2.6.0")], timeout=10)

        assert result[0]["license"] is None

    def test_caps_lookups_at_max_license_lookups(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"licenses": ["MIT"]}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        packages = [("PyPI", f"pkg{i}", "1.0.0") for i in range(50)]
        with patch("src.collectors.dependency_audit.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            with patch("src.collectors.dependency_audit._MAX_LICENSE_LOOKUPS", 5):
                result = _query_licenses(packages, timeout=10)

        assert len(result) == 5
