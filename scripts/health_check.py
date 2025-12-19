"""Standalone health check script."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.health_check import HealthChecker
import json


def main():
    """Run comprehensive health check."""
    print("🏥 DrRepo Health Check\n")
    
    # Run all checks
    health_status = HealthChecker.check_all()
    
    # Print results
    print(f"Overall Status: {health_status['status'].upper()}")
    print(f"Timestamp: {health_status['timestamp']}")
    print(f"Provider: {health_status['provider']}\n")
    
    print("Component Status:")
    print("-" * 60)
    
    components = health_status.get('components', {})
    
    for name, details in components.items():
        status = details.get('status', 'unknown')
        icon = "✅" if status == "up" else "⚠️" if status == "degraded" else "❌"
        
        print(f"{icon} {name}: {status.upper()}")
        
        if 'latency_ms' in details:
            print(f"   Latency: {details['latency_ms']}ms")
        
        if 'rate_limit_remaining' in details:
            print(f"   Rate Limit: {details['rate_limit_remaining']}/{details.get('rate_limit_total', '?')}")
        
        if details.get('error'):
            print(f"   Error: {details['error']}")
        
        print()
    
    # Return exit code
    return 0 if health_status['status'] == 'healthy' else 1


if __name__ == "__main__":
    sys.exit(main())
