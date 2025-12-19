"""Tests for custom exceptions."""

import pytest

from src.utils.exceptions import (
    DrRepoException,
    APIConnectionError,
    ConfigurationError,
    RepositoryNotFoundError,
    RateLimitError,
    AnalysisError,
    ValidationError,
    ToolExecutionError,
    AgentExecutionError
)


class TestCustomExceptions:
    """Test custom exception classes."""

    def test_base_exception(self):
        """Test DrRepoException base class."""
        exc = DrRepoException("Test error")
        assert str(exc) == "Test error"
        assert isinstance(exc, Exception)

    def test_api_connection_error(self):
        """Test APIConnectionError."""
        exc = APIConnectionError("Connection failed")
        assert isinstance(exc, DrRepoException)
        assert str(exc) == "Connection failed"

    def test_configuration_error(self):
        """Test ConfigurationError."""
        exc = ConfigurationError("Invalid config")
        assert isinstance(exc, DrRepoException)

    def test_repository_not_found_error(self):
        """Test RepositoryNotFoundError."""
        exc = RepositoryNotFoundError("Repo not found")
        assert isinstance(exc, DrRepoException)

    def test_rate_limit_error(self):
        """Test RateLimitError with retry_after."""
        exc = RateLimitError("Rate limit exceeded", retry_after=3600)
        assert isinstance(exc, DrRepoException)
        assert exc.retry_after == 3600

    def test_rate_limit_error_without_retry(self):
        """Test RateLimitError without retry_after."""
        exc = RateLimitError("Rate limit exceeded")
        assert exc.retry_after is None

    def test_validation_error(self):
        """Test ValidationError."""
        exc = ValidationError("Invalid input")
        assert isinstance(exc, DrRepoException)

    def test_tool_execution_error(self):
        """Test ToolExecutionError."""
        original = ValueError("Original error")
        exc = ToolExecutionError("GitHubTool", "Execution failed", original)
        
        assert isinstance(exc, DrRepoException)
        assert exc.tool_name == "GitHubTool"
        assert exc.original_error == original
        assert "GitHubTool" in str(exc)

    def test_agent_execution_error(self):
        """Test AgentExecutionError."""
        original = RuntimeError("Agent crashed")
        exc = AgentExecutionError("RepoAnalyzer", "Analysis failed", original)
        
        assert isinstance(exc, DrRepoException)
        assert exc.agent_name == "RepoAnalyzer"
        assert exc.original_error == original
        assert "RepoAnalyzer" in str(exc)

    def test_exception_inheritance(self):
        """Test that all custom exceptions inherit from DrRepoException."""
        exceptions = [
            APIConnectionError("test"),
            ConfigurationError("test"),
            RepositoryNotFoundError("test"),
            RateLimitError("test"),
            AnalysisError("test"),
            ValidationError("test"),
            ToolExecutionError("tool", "test"),
            AgentExecutionError("agent", "test")
        ]
        
        for exc in exceptions:
            assert isinstance(exc, DrRepoException)
            assert isinstance(exc, Exception)
