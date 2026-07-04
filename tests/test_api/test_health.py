"""Tests for the FastAPI health check endpoints.

`src.api.health` loads its `Config` once at import time (it IS a real
entrypoint, per the DI design) -- tests monkeypatch the module-level
`_config` directly rather than touching real environment variables.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.health import app
from src.config import Config

client = TestClient(app)


class TestHealthEndpoints:
    def test_root_returns_service_info(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["service"] == "DrRepo Health Check API"

    def test_liveness_always_200(self):
        response = client.get("/health/live")
        assert response.status_code == 200

    def test_simple_health_check_ok(self):
        response = client.get("/health/simple")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_readiness_fails_when_config_incomplete(self):
        with patch("src.api.health._config", Config(model_provider="groq", groq_api_key="")):
            response = client.get("/health/ready")
        assert response.status_code == 503

    def test_readiness_ok_when_config_complete(self):
        with patch("src.api.health._config", Config(model_provider="groq", groq_api_key="present")):
            response = client.get("/health/ready")
        assert response.status_code == 200

    @patch("src.utils.health_check.HealthChecker.check_all")
    def test_health_endpoint_returns_200_when_healthy(self, mock_check_all):
        mock_check_all.return_value = {
            "status": "healthy",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "version": "2.0.0",
            "provider": "groq",
            "components": {},
        }
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @patch("src.utils.health_check.HealthChecker.check_all")
    def test_health_endpoint_returns_503_when_degraded(self, mock_check_all):
        mock_check_all.return_value = {
            "status": "degraded",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "version": "2.0.0",
            "provider": "groq",
            "components": {"github_api": {"status": "down"}},
        }
        response = client.get("/health")
        assert response.status_code == 503

    @patch("src.utils.health_check.HealthChecker.check_all")
    def test_health_endpoint_handles_exception(self, mock_check_all):
        mock_check_all.side_effect = Exception("boom")
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["error"] == "boom"

    @patch("src.utils.health_check.HealthChecker.check_all")
    def test_components_endpoint(self, mock_check_all):
        mock_check_all.return_value = {"components": {"github_api": {"status": "up"}}}
        response = client.get("/health/components")
        assert response.status_code == 200
        assert response.json()["github_api"]["status"] == "up"
