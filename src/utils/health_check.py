"""Health check utilities for monitoring system components.

All checks take an explicit `Config` argument (dependency injection) instead
of importing a global singleton, so they're trivially testable with a fake
config and never touch real environment variables in tests.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import httpx

from src.config import Config
from src.utils.logger import logger


class HealthChecker:
    """Centralized health checking for all system components."""

    @staticmethod
    def check_groq(config: Config) -> Tuple[bool, Dict]:
        """Check Groq API health.

        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        if config.model_provider != "groq":
            return True, {"status": "not_used", "message": "Using different provider"}

        try:
            start_time = time.time()

            from langchain_groq import ChatGroq
            from pydantic import SecretStr

            llm = ChatGroq(
                model=config.model_name, api_key=SecretStr(config.groq_api_key), timeout=5
            )
            llm.invoke("ping")

            latency_ms = int((time.time() - start_time) * 1000)

            logger.info("Groq API health check: OK")
            return True, {"status": "up", "latency_ms": latency_ms, "model": config.model_name}

        except Exception as e:
            logger.error(f"Groq API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__,
            }

    @staticmethod
    def check_openai(config: Config) -> Tuple[bool, Dict]:
        """Check OpenAI API health.

        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        if config.model_provider != "openai":
            return True, {"status": "not_used", "message": "Using different provider"}

        try:
            start_time = time.time()

            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr

            llm = ChatOpenAI(
                model=config.model_name, api_key=SecretStr(config.openai_api_key), timeout=5
            )
            llm.invoke("ping")

            latency_ms = int((time.time() - start_time) * 1000)

            logger.info("OpenAI API health check: OK")
            return True, {"status": "up", "latency_ms": latency_ms, "model": config.model_name}

        except Exception as e:
            logger.error(f"OpenAI API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__,
            }

    @staticmethod
    def check_github(config: Config) -> Tuple[bool, Dict]:
        """Check GitHub API health.

        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        try:
            start_time = time.time()

            from github import Auth, Github

            auth = Auth.Token(config.github_token)
            github = Github(auth=auth, timeout=5)

            rate_limit = github.get_rate_limit()

            # PyGithub >=2.4 removed the `.core` shortcut from RateLimitOverview;
            # the equivalent is `.resources.core` (or the `.rate` alias).
            core = rate_limit.resources.core
            core_remaining = core.remaining
            core_limit = core.limit

            latency_ms = int((time.time() - start_time) * 1000)

            is_healthy = core_remaining > 10

            logger.info(f"GitHub API health check: OK (remaining: {core_remaining})")
            return is_healthy, {
                "status": "up" if is_healthy else "degraded",
                "latency_ms": latency_ms,
                "rate_limit_remaining": core_remaining,
                "rate_limit_total": core_limit,
                "warning": "Low rate limit" if core_remaining < 100 else None,
            }

        except Exception as e:
            logger.error(f"GitHub API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__,
            }

    @staticmethod
    def check_osv_connectivity(config: Config) -> Tuple[bool, Dict]:
        """Check network connectivity used by dependency-audit collectors (OSV.dev).

        v2 no longer depends on Tavily; this checks that outbound HTTPS calls
        (the same path OSV lookups use) succeed.

        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        try:
            start_time = time.time()

            resp = httpx.get("https://api.osv.dev/v1/query", timeout=5)
            # Any HTTP response (even 4xx for a malformed GET) proves connectivity.
            latency_ms = int((time.time() - start_time) * 1000)
            _ = resp.status_code

            logger.info("OSV.dev connectivity check: OK")
            return True, {"status": "up", "latency_ms": latency_ms}

        except Exception as e:
            logger.error(f"OSV.dev connectivity check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__,
            }

    @staticmethod
    def check_all(config: Config) -> Dict:
        """Run all health checks and return comprehensive status.

        Returns:
            Dictionary with overall status and individual component details
        """
        components = {}
        all_healthy = True

        if config.model_provider == "groq":
            is_healthy, details = HealthChecker.check_groq(config)
            components["llm_groq"] = details
        else:
            is_healthy, details = HealthChecker.check_openai(config)
            components["llm_openai"] = details
        all_healthy = all_healthy and is_healthy

        is_healthy, details = HealthChecker.check_github(config)
        components["github_api"] = details
        all_healthy = all_healthy and is_healthy

        is_healthy, details = HealthChecker.check_osv_connectivity(config)
        components["osv_connectivity"] = details
        all_healthy = all_healthy and is_healthy

        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "provider": config.model_provider,
            "components": components,
        }
