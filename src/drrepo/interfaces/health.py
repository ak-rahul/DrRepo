"""Connectivity checks (LLM provider, GitHub, OSV.dev) and the FastAPI health app.

No check spends LLM tokens: provider health is probed via the `/models` listing
endpoint, which validates the key without running a completion. Checks take an
explicit `Config` and an injectable `httpx.Client`, so tests use fakes.

The FastAPI `app` (served by `drrepo health-api`) never runs an analysis: it
exposes liveness, readiness (config valid), and these checks. Endpoints are
plain `def` so FastAPI runs the blocking checks in its threadpool instead of
stalling the event loop. Config loads on first request, not at import.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from drrepo import __version__
from drrepo.config import Config

_TIMEOUT = 5.0
_PROVIDER_MODELS_URL = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}


def _list_models(config: Config, client: httpx.Client) -> tuple[int, set[str]]:
    """(HTTP status, model ids offered). Spends no tokens: model listing only."""
    if config.model_provider == "ollama":
        resp = client.get(f"{config.ollama_base_url.rstrip('/')}/api/tags")
        if resp.status_code != 200:
            return resp.status_code, set()
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        # "llama3.1:latest" also answers to "llama3.1".
        return 200, names | {n.removesuffix(":latest") for n in names}
    if config.model_provider == "anthropic":
        headers = {"x-api-key": config.api_key(), "anthropic-version": "2023-06-01"}
    else:
        headers = {"Authorization": f"Bearer {config.api_key()}"}
    resp = client.get(_PROVIDER_MODELS_URL[config.model_provider], headers=headers)
    if resp.status_code != 200:
        return resp.status_code, set()
    return 200, {m.get("id") for m in resp.json().get("data", [])}


@dataclass
class ComponentHealth:
    name: str
    status: str  # "up" | "degraded" | "down" | "not_configured"
    latency_ms: int | None = None
    detail: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.status in ("up", "degraded")


def _timed(name: str, probe: Callable[[], ComponentHealth]) -> ComponentHealth:
    start = time.perf_counter()
    try:
        result = probe()
    except Exception as e:
        result = ComponentHealth(
            name=name, status="down", detail=f"{type(e).__name__}: {str(e)[:120]}"
        )
    if result.latency_ms is None and result.status != "not_configured":
        result.latency_ms = int((time.perf_counter() - start) * 1000)
    return result


def check_llm(config: Config, client: httpx.Client) -> ComponentHealth:
    """Reachability of the provider, and that it offers every model configured per role."""
    name = f"llm_{config.model_provider}"

    def probe() -> ComponentHealth:
        missing_key = config.validate_for_llm()
        if missing_key:
            return ComponentHealth(name, "not_configured", detail=f"{missing_key[0]} not set")
        status, offered = _list_models(config, client)
        if status == 401:
            return ComponentHealth(name, "down", detail="API key rejected (401)")
        if status == 429:
            return ComponentHealth(name, "degraded", detail="rate limited (429)")
        if status != 200:
            return ComponentHealth(name, "down", detail=f"model listing returned HTTP {status}")
        roles = config.models_by_role()
        unavailable = sorted({m for m in roles.values() if m not in offered})
        if unavailable:
            return ComponentHealth(
                name, "degraded", detail=f"model(s) not offered by provider: {unavailable}"
            )
        return ComponentHealth(name, "up", extra={"models": roles})

    return _timed(name, probe)


def check_github(config: Config, client: httpx.Client) -> ComponentHealth:
    def probe() -> ComponentHealth:
        headers = {"Accept": "application/vnd.github+json"}
        if config.github_token:
            headers["Authorization"] = f"Bearer {config.github_token}"
        resp = client.get("https://api.github.com/rate_limit", headers=headers)
        if resp.status_code == 401:
            return ComponentHealth("github_api", "down", detail="GH_TOKEN rejected (401)")
        resp.raise_for_status()
        core = resp.json().get("resources", {}).get("core", {})
        remaining, limit = int(core.get("remaining", 0)), int(core.get("limit", 0))
        status = "up" if remaining > 50 else "degraded"
        detail = None if config.github_token else "unauthenticated (set GH_TOKEN for 5000 req/h)"
        return ComponentHealth(
            "github_api",
            status,
            detail=detail,
            extra={"rate_limit_remaining": remaining, "rate_limit": limit},
        )

    return _timed("github_api", probe)


def check_osv(client: httpx.Client) -> ComponentHealth:
    def probe() -> ComponentHealth:
        resp = client.post(
            "https://api.osv.dev/v1/query",
            json={"package": {"name": "jinja2", "ecosystem": "PyPI"}, "version": "2.4.1"},
        )
        resp.raise_for_status()
        return ComponentHealth("osv_api", "up")

    return _timed("osv_api", probe)


def check_all(config: Config, client: httpx.Client | None = None) -> dict[str, Any]:
    """Run every check; `status` is "healthy" only if all components are up."""
    own_client = client is None
    http = client or httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": "drrepo-health"})
    try:
        components = [check_llm(config, http), check_github(config, http), check_osv(http)]
    finally:
        if own_client:
            http.close()

    if all(c.status == "up" for c in components):
        overall = "healthy"
    elif all(c.healthy for c in components):
        overall = "degraded"
    else:
        overall = "unhealthy"
    return {
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": __version__,
        "provider": config.model_provider,
        "components": {
            c.name: {k: v for k, v in asdict(c).items() if k != "name"} for c in components
        },
    }


# ------------------------------------------------------------- FastAPI ---

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
