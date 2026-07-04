"""Standalone health check script."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config  # noqa: E402
from src.utils.health_check import HealthChecker  # noqa: E402


def main():
    """Run comprehensive health check."""
    print("DrRepo Health Check\n")

    config = Config.from_env()
    health_status = HealthChecker.check_all(config)

    print(f"Overall Status: {health_status['status'].upper()}")
    print(f"Timestamp: {health_status['timestamp']}")
    print(f"Provider: {health_status['provider']}\n")

    print("Component Status:")
    print("-" * 60)

    for name, details in health_status.get("components", {}).items():
        status = details.get("status", "unknown")
        icon = "OK  " if status in ("up", "not_used") else "WARN" if status == "degraded" else "FAIL"

        print(f"{icon} {name}: {status.upper()}")
        if "latency_ms" in details:
            print(f"     Latency: {details['latency_ms']}ms")
        if "rate_limit_remaining" in details:
            print(f"     Rate Limit: {details['rate_limit_remaining']}/{details.get('rate_limit_total', '?')}")
        if details.get("error"):
            print(f"     Error: {details['error']}")
        print()

    return 0 if health_status["status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
