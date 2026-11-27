"""FastAPI health endpoint for infrastructure probes.

It never runs an analysis -- only liveness, readiness (config valid), and
dependency connectivity. Run with `drrepo health-api` (or any ASGI server via
`drrepo.interfaces.health_api:app`).

Endpoints are plain `def`, not `async def`: the checks do blocking network I/O,
and FastAPI runs sync endpoints in a threadpool instead of blocking the event loop.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from drrepo import __version__
from drrepo.config import Config
from drrepo.interfaces.health_checks import check_all

app = FastAPI(
    title="DrRepo Health API",
    description="Liveness, readiness, and dependency connectivity for DrRepo deployments.",
    version=__version__,
)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Loaded on first request (not at import), so importing the app has no side effects."""
    return Config.from_env()


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "DrRepo Health API",
        "version": __version__,
        "endpoints": {
            "/health": "Full dependency check (LLM provider, GitHub, OSV.dev)",
            "/health/live": "Process is alive",
            "/health/ready": "Configuration is valid for running analyses",
        },
    }


@app.get("/health/live", response_class=PlainTextResponse)
def live() -> str:
    return "alive"


@app.get("/health/ready")
def ready() -> JSONResponse:
    try:
        missing = get_config().validate_for_llm()
    except Exception as e:  # invalid configuration is "not ready", not a 500
        return JSONResponse({"ready": False, "error": str(e)}, status_code=503)
    if missing:
        return JSONResponse({"ready": False, "missing": missing}, status_code=503)
    return JSONResponse({"ready": True})


@app.get("/health")
def health() -> JSONResponse:
    try:
        status = check_all(get_config())
    except Exception as e:
        return JSONResponse(
            {"status": "unhealthy", "error": f"{type(e).__name__}: {e}"}, status_code=503
        )
    return JSONResponse(status, status_code=200 if status["status"] != "unhealthy" else 503)
