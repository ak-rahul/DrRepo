"""Health check API endpoint for production monitoring."""

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from datetime import datetime
import json

from src.utils.health_check import HealthChecker
from src.utils.logger import logger

app = FastAPI(
    title="DrRepo Health Check API",
    description="Health monitoring endpoint for DrRepo system components",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "DrRepo Health Check API",
        "version": "1.0.0",
        "endpoints": {
            "/health": "Comprehensive health check",
            "/health/simple": "Simple health status",
            "/health/components": "Individual component status"
        }
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint.
    
    Returns:
        JSON response with detailed system health status
        - 200 OK: All components healthy
        - 503 Service Unavailable: One or more components degraded/down
    
    Example Response:
        {
            "status": "healthy",
            "timestamp": "2025-12-19T08:00:00Z",
            "version": "1.0.0",
            "provider": "groq",
            "components": {
                "llm_groq": {"status": "up", "latency_ms": 120},
                "github_api": {"status": "up", "latency_ms": 85},
                "tavily_api": {"status": "up", "latency_ms": 200},
                "rag_retriever": {"status": "up", "latency_ms": 45}
            }
        }
    """
    try:
        logger.info("Health check requested")
        
        # Run all health checks
        health_status = HealthChecker.check_all()
        
        # Determine HTTP status code
        overall_status = health_status.get("status", "degraded")
        status_code = 200 if overall_status == "healthy" else 503
        
        logger.info(f"Health check completed: {overall_status}")
        
        return Response(
            content=json.dumps(health_status, indent=2),
            status_code=status_code,
            media_type="application/json"
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        
        error_response = {
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "error_type": type(e).__name__
        }
        
        return Response(
            content=json.dumps(error_response, indent=2),
            status_code=503,
            media_type="application/json"
        )


@app.get("/health/simple")
async def simple_health_check():
    """Simple health check endpoint (fast response).
    
    Returns:
        JSON with basic status only (no component details)
        - 200 OK: System is operational
        - 503 Service Unavailable: System has issues
    
    Example Response:
        {"status": "healthy", "timestamp": "2025-12-19T08:00:00Z"}
    """
    try:
        # Just check if we can import key modules (fast check)
        from src.utils.config import config
        from src.tools.github_tool import GitHubTool
        
        return JSONResponse(
            content={
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat()
            },
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Simple health check failed: {str(e)}")
        
        return JSONResponse(
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            },
            status_code=503
        )


@app.get("/health/components")
async def component_health():
    """Individual component health status.
    
    Returns:
        JSON with detailed status for each component
    
    Example Response:
        {
            "llm_groq": {"status": "up", "latency_ms": 120},
            "github_api": {"status": "up", "rate_limit_remaining": 4500},
            "tavily_api": {"status": "up", "latency_ms": 200},
            "rag_retriever": {"status": "up", "latency_ms": 45}
        }
    """
    try:
        health_status = HealthChecker.check_all()
        components = health_status.get("components", {})
        
        return JSONResponse(
            content=components,
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Component health check failed: {str(e)}")
        
        return JSONResponse(
            content={"error": str(e)},
            status_code=503
        )


@app.get("/health/ready")
async def readiness_check():
    """Kubernetes-style readiness probe.
    
    Returns:
        200 if ready to accept traffic, 503 otherwise
    """
    try:
        # Check critical components only
        from src.utils.config import config
        
        if not config.validate():
            raise ValueError("Configuration validation failed")
        
        return Response(status_code=200, content="ready")
        
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        return Response(status_code=503, content="not ready")


@app.get("/health/live")
async def liveness_check():
    """Kubernetes-style liveness probe.
    
    Returns:
        200 if service is alive (even if degraded)
    """
    # Simple check - if we can respond, we're alive
    return Response(status_code=200, content="alive")


if __name__ == "__main__":
    import uvicorn
    
    # Run development server
    uvicorn.run(
        "src.api.health:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
