"""Tests for circuit breaker pattern."""

import pytest
import time
from unittest.mock import Mock

from src.utils.circuit_breaker import CircuitBreaker, CircuitState, circuit_breaker
from src.utils.exceptions import APIConnectionError


class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    def test_closed_state_success(self):
        """Test successful execution in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=1)
        mock_func = Mock(return_value="success")
        
        result = breaker.call(mock_func)
        
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_closed_to_open_transition(self):
        """Test transition from CLOSED to OPEN after threshold."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=1)
        mock_func = Mock(side_effect=Exception("Error"))
        
        # Fail 3 times to reach threshold
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_open_state_rejects_calls(self):
        """Test that OPEN state rejects calls immediately."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=10)
        mock_func = Mock(side_effect=Exception("Error"))
        
        # Reach OPEN state
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Next call should be rejected without calling func
        with pytest.raises(APIConnectionError, match="Circuit breaker is OPEN"):
            breaker.call(mock_func)
        
        # Func should only be called twice (during failures), not on rejection
        assert mock_func.call_count == 2

    def test_half_open_recovery(self):
        """Test recovery from OPEN to CLOSED via HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)
        mock_func = Mock(side_effect=[
            Exception("Error"),
            Exception("Error"),
            "success"  # Success after timeout
        ])
        
        # Reach OPEN state
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Next call should transition to HALF_OPEN and succeed
        result = breaker.call(mock_func)
        
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_manual_reset(self):
        """Test manual circuit breaker reset."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=10)
        mock_func = Mock(side_effect=Exception("Error"))
        
        # Reach OPEN state
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Manual reset
        breaker.reset()
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_get_state(self):
        """Test get_state method."""
        breaker = CircuitBreaker(failure_threshold=5, timeout=60, name="TestBreaker")
        
        state = breaker.get_state()
        
        assert state["name"] == "TestBreaker"
        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["failure_threshold"] == 5
        assert state["timeout"] == 60

    def test_decorator(self):
        """Test circuit breaker decorator."""
        @circuit_breaker(failure_threshold=2, timeout=1)
        def test_func(should_fail=False):
            if should_fail:
                raise Exception("Failed")
            return "success"
        
        # Should succeed
        result = test_func(should_fail=False)
        assert result == "success"
        
        # Fail twice to open circuit
        for _ in range(2):
            with pytest.raises(Exception):
                test_func(should_fail=True)
        
        # Circuit should be open
        assert test_func.circuit_breaker.state == CircuitState.OPEN
        
        # Should reject next call
        with pytest.raises(APIConnectionError):
            test_func(should_fail=False)

    def test_specific_exception_type(self):
        """Test circuit breaker with specific exception type."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            timeout=1,
            expected_exception=ValueError
        )
        
        # ValueError should count as failure
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("Error")))
        
        assert breaker.failure_count == 1
        
        # Other exceptions should not count
        with pytest.raises(KeyError):
            breaker.call(lambda: (_ for _ in ()).throw(KeyError("Different error")))
        
        # Failure count should still be 1 (KeyError didn't count)
        assert breaker.failure_count == 1
