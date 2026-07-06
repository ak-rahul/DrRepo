"""Health check API endpoint for production monitoring."""

import json
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from src.config import Config
from src.utils.health_check import HealthChecker
from src.utils.logger import logger

app = FastAPI(
    title="DrRepo Health Check API",
    description="Health monitoring endpoint for DrRepo system components",
    version="3.0.0",
)

# Loaded once at import time -- this module IS the real entrypoint, so this is
# the one place `Config.from_env()` is allowed to be called eagerly.
_config = Config.from_env()


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "DrRepo Health Check API",
        "version": "3.0.0",
        "endpoints": {
            "/health": "Comprehensive health check",
            "/health/simple": "Simple health status",
            "/health/components": "Individual component status",
        },
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint.

    Returns:
        JSON response with detailed system health status
        - 200 OK: All components healthy
        - 503 Service Unavailable: One or more components degraded/down
    """
    try:
        logger.info("Health check requested")

        health_status = HealthChecker.check_all(_config)

        overall_status = health_status.get("status", "degraded")
        status_code = 200 if overall_status == "healthy" else 503

        logger.info(f"Health check completed: {overall_status}")

        return Response(
            content=json.dumps(health_status, indent=2),
            status_code=status_code,
            media_type="application/json",
        )

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)

        error_response = {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "error_type": type(e).__name__,
        }

        return Response(
            content=json.dumps(error_response, indent=2),
            status_code=503,
            media_type="application/json",
        )


@app.get("/health/simple")
async def simple_health_check():
    """Simple health check endpoint (fast response, no external calls).

    Returns:
        200 OK if the process can import its core modules; 503 otherwise.
    """
    try:
        from src.collectors.github_metadata import parse_repo_path  # noqa: F401

        return JSONResponse(
            content={"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()},
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Simple health check failed: {str(e)}")

        return JSONResponse(
            content={
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            },
            status_code=503,
        )


@app.get("/health/components")
async def component_health():
    """Individual component health status."""
    try:
        health_status = HealthChecker.check_all(_config)
        return JSONResponse(content=health_status.get("components", {}), status_code=200)

    except Exception as e:
        logger.error(f"Component health check failed: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=503)


@app.get("/health/ready")
async def readiness_check():
    """Kubernetes-style readiness probe.

    Returns:
        200 if ready to accept traffic, 503 otherwise
    """
    missing = _config.validate_for_llm()
    if missing:
        logger.error(f"Readiness check failed: missing {missing}")
        return Response(status_code=503, content="not ready")
    return Response(status_code=200, content="ready")


@app.get("/health/live")
async def liveness_check():
    """Kubernetes-style liveness probe.

    Returns:
        200 if service is alive (even if degraded)
    """
    return Response(status_code=200, content="alive")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.health:app", host="0.0.0.0", port=8000, log_level="info")
