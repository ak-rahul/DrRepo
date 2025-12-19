"""Tests for health check utilities."""

import pytest
from unittest.mock import Mock, patch

from src.utils.health_check import HealthChecker


class TestHealthChecker:
    """Test cases for HealthChecker."""

    @patch('src.utils.health_check.ChatGroq')
    def test_check_groq_healthy(self, mock_groq):
        """Test successful Groq health check."""
        # Mock successful LLM call
        mock_llm = Mock()
        mock_llm.invoke.return_value = "pong"
        mock_groq.return_value = mock_llm
        
        is_healthy, details = HealthChecker.check_groq()
        
        assert is_healthy is True
        assert details["status"] == "up"
        assert "latency_ms" in details
        assert details["latency_ms"] >= 0

    @patch('src.utils.health_check.ChatGroq')
    def test_check_groq_failure(self, mock_groq):
        """Test failed Groq health check."""
        # Mock LLM failure
        mock_groq.side_effect = Exception("API connection failed")
        
        is_healthy, details = HealthChecker.check_groq()
        
        assert is_healthy is False
        assert details["status"] == "down"
        assert "error" in details

    @patch('src.utils.health_check.Github')
    def test_check_github_healthy(self, mock_github):
        """Test successful GitHub health check."""
        # Mock rate limit response
        mock_rate_limit = Mock()
        mock_rate_limit.core.remaining = 5000
        mock_rate_limit.core.limit = 5000
        
        mock_gh = Mock()
        mock_gh.get_rate_limit.return_value = mock_rate_limit
        mock_github.return_value = mock_gh
        
        is_healthy, details = HealthChecker.check_github()
        
        assert is_healthy is True
        assert details["status"] == "up"
        assert details["rate_limit_remaining"] == 5000

    @patch('src.utils.health_check.Github')
    def test_check_github_low_rate_limit(self, mock_github):
        """Test GitHub health check with low rate limit."""
        # Mock low rate limit
        mock_rate_limit = Mock()
        mock_rate_limit.core.remaining = 5  # Below threshold
        mock_rate_limit.core.limit = 5000
        
        mock_gh = Mock()
        mock_gh.get_rate_limit.return_value = mock_rate_limit
        mock_github.return_value = mock_gh
        
        is_healthy, details = HealthChecker.check_github()
        
        assert is_healthy is False
        assert details["status"] == "degraded"
        assert details["rate_limit_remaining"] == 5

    def test_check_all(self):
        """Test comprehensive health check."""
        health_status = HealthChecker.check_all()
        
        assert "status" in health_status
        assert "timestamp" in health_status
        assert "version" in health_status
        assert "components" in health_status
        
        components = health_status["components"]
        
        # Should have at least LLM and other components
        assert len(components) >= 3
