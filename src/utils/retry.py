"""Retry decorator with exponential backoff for handling transient failures."""

import time
import functools
from typing import Callable, Type, Tuple, Optional
from src.utils.logger import logger


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None
):
    """Retry decorator with exponential backoff for handling transient failures.
    
    Automatically retries failed function calls with increasing wait times between
    attempts. Useful for handling temporary network issues, API rate limits, and
    other transient errors.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_factor: Multiplier for wait time between retries (default: 2.0)
        initial_delay: Initial wait time in seconds (default: 1.0)
        max_delay: Maximum wait time in seconds (default: 60.0)
        exceptions: Tuple of exception types to catch and retry (default: (Exception,))
        on_retry: Optional callback function called on each retry with signature:
                  on_retry(attempt: int, exception: Exception, wait_time: float)
    
    Returns:
        Decorated function with retry logic
    
    Example:
        ```
        from github import GithubException
        
        @retry_with_backoff(
            max_retries=3,
            exceptions=(GithubException, ConnectionError)
        )
        def fetch_repo(url):
            return github_client.get_repo(url)
        ```
    
    Retry Schedule (with defaults):
        - Attempt 1: Immediate execution
        - Attempt 2: Wait 1.0s
        - Attempt 3: Wait 2.0s
        - Attempt 4: Wait 4.0s (final attempt)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):  # +1 for initial attempt
                try:
                    # Execute the function
                    result = func(*args, **kwargs)
                    
                    # Log success if this was a retry
                    if attempt > 0:
                        logger.info(
                            f"{func.__name__} succeeded on attempt {attempt + 1}/{max_retries + 1}"
                        )
                    
                    return result
                    
                except exceptions as e:
                    last_exception = e
                    
                    # If this was the last attempt, raise the exception
                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {str(e)}"
                        )
                        raise
                    
                    # Calculate wait time with exponential backoff
                    wait_time = min(
                        initial_delay * (backoff_factor ** attempt),
                        max_delay
                    )
                    
                    # Log retry information
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {str(e)}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    
                    # Call optional retry callback
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e, wait_time)
                        except Exception as callback_error:
                            logger.error(f"Retry callback failed: {callback_error}")
                    
                    # Wait before next retry
                    time.sleep(wait_time)
            
            # This should never be reached, but just in case
            raise last_exception
        
        return wrapper
    return decorator


def retry_on_rate_limit(max_retries: int = 5, initial_delay: float = 60.0):
    """Specialized retry decorator for API rate limit errors.
    
    Uses longer delays suitable for API rate limiting scenarios.
    
    Args:
        max_retries: Maximum retry attempts (default: 5)
        initial_delay: Initial wait time in seconds (default: 60)
    
    Returns:
        Decorated function with rate limit retry logic
    
    Example:
        ```
        @retry_on_rate_limit(max_retries=3, initial_delay=60)
        def search_web(query):
            return tavily_client.search(query)
        ```
    """
    def rate_limit_callback(attempt: int, exception: Exception, wait_time: float):
        """Log rate limit specific information."""
        logger.info(f"Rate limit hit. Waiting {wait_time}s before retry {attempt}")
    
    return retry_with_backoff(
        max_retries=max_retries,
        backoff_factor=1.5,  # Slower backoff for rate limits
        initial_delay=initial_delay,
        max_delay=300.0,  # Max 5 minutes
        exceptions=(Exception,),  # Catch all - rate limit exceptions vary by API
        on_retry=rate_limit_callback
    )


def retry_on_network_error(max_retries: int = 3):
    """Specialized retry decorator for network-related errors.
    
    Uses shorter delays suitable for transient network issues.
    
    Args:
        max_retries: Maximum retry attempts (default: 3)
    
    Returns:
        Decorated function with network error retry logic
    
    Example:
        ```
        @retry_on_network_error(max_retries=3)
        def download_file(url):
            return requests.get(url)
        ```
    """
    import requests
    
    return retry_with_backoff(
        max_retries=max_retries,
        backoff_factor=2.0,
        initial_delay=1.0,
        max_delay=30.0,
        exceptions=(
            ConnectionError,
            TimeoutError,
            requests.exceptions.RequestException,
        )
    )
