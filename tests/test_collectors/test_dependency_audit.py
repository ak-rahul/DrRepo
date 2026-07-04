"""Tests for the dependency audit collector (manifest parsing + OSV.dev)."""

from unittest.mock import Mock, patch

from src.collectors.dependency_audit import (
    _parse_package_json,
    _parse_pyproject_toml,
    _parse_requirements_txt,
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
