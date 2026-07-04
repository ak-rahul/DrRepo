"""Tests for health check utilities.

All checks take an injected `fake_config` fixture (no real credentials), and
every external call is mocked -- including `test_check_all`, which in v1 made
live network calls to Groq/GitHub/Tavily and loaded a real embeddings model
from inside what was supposed to be a unit test.
"""

from unittest.mock import Mock, patch

from src.utils.health_check import HealthChecker


class TestHealthChecker:
    @patch("langchain_groq.ChatGroq")
    def test_check_groq_healthy(self, mock_groq, fake_config):
        mock_llm = Mock()
        mock_llm.invoke.return_value = "pong"
        mock_groq.return_value = mock_llm

        is_healthy, details = HealthChecker.check_groq(fake_config)

        assert is_healthy is True
        assert details["status"] == "up"
        assert "latency_ms" in details
        assert details["latency_ms"] >= 0

    @patch("langchain_groq.ChatGroq")
    def test_check_groq_failure(self, mock_groq, fake_config):
        mock_groq.side_effect = Exception("API connection failed")

        is_healthy, details = HealthChecker.check_groq(fake_config)

        assert is_healthy is False
        assert details["status"] == "down"
        assert "error" in details

    def test_check_groq_not_used_when_openai_configured(self, fake_config):
        fake_config.model_provider = "openai"

        is_healthy, details = HealthChecker.check_groq(fake_config)

        assert is_healthy is True
        assert details["status"] == "not_used"

    @patch("github.Github")
    def test_check_github_healthy(self, mock_github, fake_config):
        # PyGithub >=2.4 removed `.core` in favor of `.resources.core` -- this
        # is exactly the shape that broke v1's health check in production.
        mock_rate = Mock(remaining=5000, limit=5000)
        mock_resources = Mock(core=mock_rate)
        mock_rate_limit = Mock(resources=mock_resources)

        mock_gh = Mock()
        mock_gh.get_rate_limit.return_value = mock_rate_limit
        mock_github.return_value = mock_gh

        is_healthy, details = HealthChecker.check_github(fake_config)

        assert is_healthy is True
        assert details["status"] == "up"
        assert details["rate_limit_remaining"] == 5000

    @patch("github.Github")
    def test_check_github_missing_resources_core_is_down_not_raised(self, mock_github, fake_config):
        """If PyGithub's shape ever changes again, this must degrade gracefully, not crash."""
        mock_rate_limit = Mock(spec=["rate"])  # no `.resources` attribute at all
        mock_gh = Mock()
        mock_gh.get_rate_limit.return_value = mock_rate_limit
        mock_github.return_value = mock_gh

        is_healthy, details = HealthChecker.check_github(fake_config)

        assert is_healthy is False
        assert details["status"] == "down"

    @patch("github.Github")
    def test_check_github_failure(self, mock_github, fake_config):
        mock_github.side_effect = Exception("Authentication failed")

        is_healthy, details = HealthChecker.check_github(fake_config)

        assert is_healthy is False
        assert details["status"] == "down"
        assert "error" in details

    @patch("src.utils.health_check.httpx.get")
    def test_check_osv_connectivity_ok(self, mock_get, fake_config):
        mock_get.return_value = Mock(status_code=400)

        is_healthy, details = HealthChecker.check_osv_connectivity(fake_config)

        assert is_healthy is True
        assert details["status"] == "up"

    @patch("src.utils.health_check.httpx.get")
    def test_check_osv_connectivity_down(self, mock_get, fake_config):
        mock_get.side_effect = ConnectionError("no network")

        is_healthy, details = HealthChecker.check_osv_connectivity(fake_config)

        assert is_healthy is False
        assert details["status"] == "down"

    @patch("src.utils.health_check.httpx.get")
    @patch("github.Github")
    @patch("langchain_groq.ChatGroq")
    def test_check_all_aggregates_all_components(
        self, mock_groq, mock_github, mock_httpx_get, fake_config
    ):
        mock_groq.return_value = Mock(invoke=Mock(return_value="pong"))
        mock_rate = Mock(remaining=5000, limit=5000)
        mock_github.return_value = Mock(
            get_rate_limit=Mock(return_value=Mock(resources=Mock(core=mock_rate)))
        )
        mock_httpx_get.return_value = Mock(status_code=400)

        health_status = HealthChecker.check_all(fake_config)

        assert health_status["status"] == "healthy"
        assert "timestamp" in health_status
        assert "version" in health_status
        components = health_status["components"]
        assert len(components) >= 3
        assert components["llm_groq"]["status"] == "up"
        assert components["github_api"]["status"] == "up"

    @patch("src.utils.health_check.httpx.get")
    @patch("github.Github")
    @patch("langchain_groq.ChatGroq")
    def test_check_all_degraded_when_one_component_down(
        self, mock_groq, mock_github, mock_httpx_get, fake_config
    ):
        mock_groq.side_effect = Exception("down")
        mock_rate = Mock(remaining=5000, limit=5000)
        mock_github.return_value = Mock(
            get_rate_limit=Mock(return_value=Mock(resources=Mock(core=mock_rate)))
        )
        mock_httpx_get.return_value = Mock(status_code=400)

        health_status = HealthChecker.check_all(fake_config)

        assert health_status["status"] == "degraded"
