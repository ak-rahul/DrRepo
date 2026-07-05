"""Tests for the ad hoc single-package OSV lookup tool."""

from unittest.mock import Mock, patch

from src.tools.dependency_tools import make_dependency_tools


class TestQueryOsvTool:
    @patch("src.collectors.dependency_audit.httpx.post")
    def test_no_vulnerabilities_found(self, mock_post, fake_config):
        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"vulns": []}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        (query_osv,) = make_dependency_tools(fake_config)
        result = query_osv.invoke({"package": "requests", "ecosystem": "PyPI", "version": "2.31.0"})

        assert "No known vulnerabilities" in result

    @patch("src.collectors.dependency_audit.httpx.post")
    def test_vulnerability_found(self, mock_post, fake_config):
        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"vulns": [{"id": "PYSEC-2018-28"}]}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        (query_osv,) = make_dependency_tools(fake_config)
        result = query_osv.invoke({"package": "requests", "ecosystem": "PyPI", "version": "2.6.0"})

        assert "PYSEC-2018-28" in result
        assert "osv.dev/vulnerability/PYSEC-2018-28" in result

    @patch("src.collectors.dependency_audit.httpx.post")
    def test_network_failure_returns_error_not_exception(self, mock_post, fake_config):
        mock_post.side_effect = ConnectionError("network down")

        (query_osv,) = make_dependency_tools(fake_config)
        result = query_osv.invoke({"package": "requests", "ecosystem": "PyPI", "version": "2.6.0"})

        assert result.startswith("ERROR")
