"""Connectivity checks for external dependencies (LLM provider, GitHub, OSV.dev).

No check spends LLM tokens: provider health is probed via the `/models` listing
endpoint, which validates the API key without running a completion. All checks
take an explicit `Config`, so tests run them against fakes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from drrepo.config import Config

_TIMEOUT = 5.0
_PROVIDER_MODELS_URL = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openai": "https://api.openai.com/v1/models",
}


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
    name = f"llm_{config.model_provider}"
    key = config.groq_api_key if config.model_provider == "groq" else config.openai_api_key

    def probe() -> ComponentHealth:
        if not key:
            return ComponentHealth(
                name, "not_configured", detail=f"{config.model_provider.upper()} API key not set"
            )
        resp = client.get(
            _PROVIDER_MODELS_URL[config.model_provider], headers={"Authorization": f"Bearer {key}"}
        )
        if resp.status_code == 401:
            return ComponentHealth(name, "down", detail="API key rejected (401)")
        if resp.status_code == 429:
            return ComponentHealth(name, "degraded", detail="rate limited (429)")
        resp.raise_for_status()
        models = {m.get("id") for m in resp.json().get("data", [])}
        if config.model_name not in models:
            return ComponentHealth(
                name, "degraded", detail=f"model {config.model_name!r} not offered by provider"
            )
        return ComponentHealth(name, "up", extra={"model": config.model_name})

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
    from drrepo import __version__

    return {
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": __version__,
        "provider": config.model_provider,
        "components": {
            c.name: {k: v for k, v in asdict(c).items() if k != "name"} for c in components
        },
    }
