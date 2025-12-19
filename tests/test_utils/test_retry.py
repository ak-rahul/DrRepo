"""Tests for retry decorator."""

import pytest
import time
from unittest.mock import Mock

from src.utils.retry import retry_with_backoff, retry_on_rate_limit


class TestRetryDecorator:
    """Test cases for retry decorator."""

    def test_successful_execution_no_retry(self):
        """Test that successful function doesn't retry."""
        mock_func = Mock(return_value="success")
        
        @retry_with_backoff(max_retries=3)
        def test_func():
            return mock_func()
        
        result = test_func()
        
        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_exception(self):
        """Test that function retries on exception."""
        mock_func = Mock(side_effect=[
            ValueError("First failure"),
            ValueError("Second failure"),
            "success"
        ])
        
        @retry_with_backoff(
            max_retries=3,
            initial_delay=0.1,  # Fast retry for testing
            exceptions=(ValueError,)
        )
        def test_func():
            return mock_func()
        
        result = test_func()
        
        assert result == "success"
        assert mock_func.call_count == 3

    def test_max_retries_exceeded(self):
        """Test that exception is raised after max retries."""
        mock_func = Mock(side_effect=ValueError("Always fails"))
        
        @retry_with_backoff(
            max_retries=2,
            initial_delay=0.1,
            exceptions=(ValueError,)
        )
        def test_func():
            return mock_func()
        
        with pytest.raises(ValueError, match="Always fails"):
            test_func()
        
        assert mock_func.call_count == 3  # Initial + 2 retries

    def test_exponential_backoff(self):
        """Test that backoff time increases exponentially."""
        call_times = []
        
        @retry_with_backoff(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=0.1,
            exceptions=(ValueError,)
        )
        def test_func():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("Retry")
            return "success"
        
        result = test_func()
        
        assert result == "success"
        assert len(call_times) == 3
        
        # Check backoff timing (approximate due to execution overhead)
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        
        assert 0.08 < delay1 < 0.15  # ~0.1s
        assert 0.18 < delay2 < 0.25  # ~0.2s

    def test_specific_exception_only(self):
        """Test that only specified exceptions trigger retry."""
        mock_func = Mock(side_effect=KeyError("Different exception"))
        
        @retry_with_backoff(
            max_retries=3,
            initial_delay=0.1,
            exceptions=(ValueError,)  # Only retry ValueError
        )
        def test_func():
            return mock_func()
        
        with pytest.raises(KeyError):
            test_func()
        
        assert mock_func.call_count == 1  # No retry for KeyError

    def test_retry_callback(self):
        """Test that retry callback is called."""
        callback_calls = []
        
        def on_retry(attempt, exception, wait_time):
            callback_calls.append((attempt, type(exception).__name__, wait_time))
        
        @retry_with_backoff(
            max_retries=2,
            initial_delay=0.1,
            exceptions=(ValueError,),
            on_retry=on_retry
        )
        def test_func():
            if len(callback_calls) < 2:
                raise ValueError("Retry")
            return "success"
        
        result = test_func()
        
        assert result == "success"
        assert len(callback_calls) == 2
        assert callback_calls[0][0] == 1  # First retry
        assert callback_calls[1][0] == 2  # Second retry


class TestRateLimitRetry:
    """Test cases for rate limit retry decorator."""

    def test_rate_limit_retry(self):
        """Test rate limit retry with longer delays."""
        mock_func = Mock(side_effect=[
            Exception("Rate limit"),
            "success"
        ])
        
        @retry_on_rate_limit(max_retries=2, initial_delay=0.1)
        def test_func():
            return mock_func()
        
        result = test_func()
        
        assert result == "success"
        assert mock_func.call_count == 2
