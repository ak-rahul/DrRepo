"""REST API (`drrepo serve`): analyses as background jobs, history, badges, health.

    POST /analyses                     queue an analysis -> 202 {id, status, links}
    GET  /analyses                     your recent jobs
    GET  /analyses/{id}                one job: status, progress, summary
    GET  /analyses/{id}/report         the finished report (?format=json|md|sarif|cdx|summary)
    GET  /repos/{owner}/{name}/history recorded runs of a repository
    GET  /repos/{owner}/{name}/report  its newest stored report (SQLite store only)
    GET  /badge/{owner}/{name}         shields.io endpoint JSON (public)
    GET  /metrics                      Prometheus text format (drrepo/metrics.py)
    GET  /health, /health/live, /health/ready   (public; see interfaces/health.py)

**Authentication.** With `API_KEYS` set, every endpoint except health and badges
needs one of them, as `X-API-Key: <key>` or `Authorization: Bearer <key>`. Each
key sees only its own jobs. Without keys, only clients on this machine are
served, and a request carrying proxy headers (`X-Forwarded-For`, `Forwarded`)
never counts as local, so a reverse proxy on the same host can't open the API to
the network.

**Limits.** `API_RATE_LIMIT_PER_HOUR` analyses per client (sliding window,
429 with `Retry-After`), `API_MAX_QUEUED` waiting jobs (503), `API_WORKERS` at
once. Each analysis can clone a repository and spend LLM tokens, so keep these
small.
"""

# No `from __future__ import annotations` here: FastAPI must resolve the endpoint
# annotations, and the `Client` dependency alias is local to `create_app`.
import hashlib
import hmac
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from drrepo import __version__
from drrepo.config import Config
from drrepo.jobs import DONE, FAILED, PENDING, JobQueue, QueueFullError
from drrepo.log import logger
from drrepo.metrics import Labels
from drrepo.models import RepoRef
from drrepo.recon.clone import validate_ref
from drrepo.report.exporters import EXPORTERS, FORMATS
from drrepo.report.synthesis import grade
from drrepo.service import AnalysisService

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_MEDIA_TYPES = {
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
    "sarif": "application/sarif+json",
    "cdx": "application/vnd.cyclonedx+json",
    "summary": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}
_HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
_BADGE_COLORS = {"A": "brightgreen", "B": "green", "C": "yellow", "D": "orange", "F": "red"}
_WINDOW_SECONDS = 3600.0


class AnalysisRequest(BaseModel):
    repo_url: str = Field(description="https://github.com/<owner>/<repo>", max_length=300)
    ref: str | None = Field(default=None, description="branch, tag, or full commit SHA")
    deep: bool | None = Field(
        default=None, description="allow LLM investigations (default: config)"
    )
    description: str = Field(default="", max_length=2000, description="focus for the investigators")


class RateLimiter:
    """At most `limit` events per client in any hour (sliding window)."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, client: str) -> float | None:
        """Record an event and return None, or the seconds until one is allowed."""
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(client, deque())
            while events and now - events[0] >= _WINDOW_SECONDS:
                events.popleft()
            if len(events) >= self.limit:
                return _WINDOW_SECONDS - (now - events[0])
            events.append(now)
            return None


def _client_id(key: str) -> str:
    """How a key is recorded on its jobs: a fingerprint, never the key itself."""
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:12]


def _presented_key(request: Request) -> str | None:
    if key := request.headers.get("x-api-key"):
        return key
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _LOOPBACK and not any(h in request.headers for h in _PROXY_HEADERS)


def _repo(owner: str, name: str) -> RepoRef:
    try:
        return RepoRef.parse(f"https://github.com/{owner}/{name}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    shown = {k: v for k, v in job.items() if k not in ("report", "client")}
    shown["links"] = {"self": f"/analyses/{job['id']}"}
    if job["status"] == DONE:
        shown["links"]["report"] = f"/analyses/{job['id']}/report"
    return shown


def create_app(
    config: Config | None = None,
    *,
    service: AnalysisService | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    """The API over one `AnalysisService` and its store. Workers start with the app."""
    config = config or Config.from_env()
    service = service or AnalysisService(config)
    queue = queue or JobQueue(
        service, service.store, workers=config.api_workers, max_queued=config.api_max_queued
    )
    limiter = RateLimiter(config.api_rate_limit_per_hour)
    keys = tuple(config.api_keys)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        queue.start()
        if not keys:
            logger.warning("API_KEYS is empty: only clients on this machine can use the API")
        try:
            yield
        finally:
            queue.shutdown()

    app = FastAPI(
        title="DrRepo API",
        description="Repository audits as background jobs, score history and badges.",
        version=__version__,
        lifespan=lifespan,
    )
    from drrepo.interfaces.health import router as health_router

    app.include_router(health_router)

    def client(request: Request) -> str:
        """The caller's identity; 401/403 when it may not use the API."""
        presented = _presented_key(request)
        if keys:
            for key in keys:
                if presented is not None and hmac.compare_digest(presented, key):
                    return _client_id(key)
            raise HTTPException(
                status_code=401,
                detail="send an API key as X-API-Key or Authorization: Bearer",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if _is_local(request):
            return "local"
        raise HTTPException(
            status_code=403, detail="set API_KEYS to serve clients on other machines"
        )

    Client = Annotated[str, Depends(client)]

    def own_job(job_id: str, who: str) -> dict[str, Any]:
        job = queue.store.job(job_id)
        if job is None or (keys and job.get("client") != who):
            raise HTTPException(status_code=404, detail="no such analysis")
        return job

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "DrRepo API",
            "version": __version__,
            "endpoints": [
                "POST /analyses",
                "GET /analyses",
                "GET /analyses/{id}",
                "GET /analyses/{id}/report",
                "GET /repos/{owner}/{name}/history",
                "GET /repos/{owner}/{name}/report",
                "GET /badge/{owner}/{name}",
                "GET /metrics",
                "GET /health",
            ],
        }

    @app.post("/analyses", status_code=202)
    def submit(body: AnalysisRequest, who: Client, response: Response) -> dict[str, Any]:
        try:
            repo = RepoRef.parse(body.repo_url)
            ref = validate_ref(body.ref) if body.ref else None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        wait = limiter.acquire(who)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"at most {limiter.limit} analyses per hour",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        request = {
            "repo_url": repo.html_url,
            "ref": ref,
            "deep": body.deep,
            "description": body.description,
        }
        try:
            job = queue.submit(request, who)
        except QueueFullError as e:
            raise HTTPException(
                status_code=503, detail=str(e), headers={"Retry-After": "60"}
            ) from e
        response.headers["Location"] = f"/analyses/{job['id']}"
        return _public_job(job)

    @app.get("/analyses")
    def list_jobs(who: Client, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> list[Any]:
        jobs = queue.store.jobs(limit=limit if not keys else 1000)
        mine = [j for j in jobs if not keys or j.get("client") == who][:limit]
        return [_public_job(j) for j in mine]

    @app.get("/analyses/{job_id}")
    def get_job(job_id: str, who: Client) -> dict[str, Any]:
        return _public_job(own_job(job_id, who))

    @app.get("/analyses/{job_id}/report")
    def get_report(
        job_id: str,
        who: Client,
        format: Annotated[str, Query(pattern="^(" + "|".join(FORMATS) + ")$")] = "json",
    ) -> Response:
        job = own_job(job_id, who)
        if job["status"] == FAILED:
            raise HTTPException(status_code=409, detail=f"the analysis failed: {job['error']}")
        if job["status"] != DONE or not job.get("report"):
            raise HTTPException(status_code=409, detail=f"the analysis is {job['status']}")
        return Response(
            EXPORTERS[format](job["report"]),
            media_type=_MEDIA_TYPES[format],
            # The HTML report carries its own CSP; this header makes it binding when served.
            headers={"Content-Security-Policy": _HTML_CSP} if format == "html" else None,
        )

    @app.get("/repos/{owner}/{name}/history")
    def history(owner: str, name: str, _who: Client) -> list[dict[str, Any]]:
        return service.store.runs(_repo(owner, name).html_url)

    @app.get("/repos/{owner}/{name}/report")
    def latest(owner: str, name: str, _who: Client) -> dict[str, Any]:
        report = service.store.latest_report(_repo(owner, name).html_url)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="no stored report (full reports are kept with STORE_BACKEND=sqlite)",
            )
        return report

    @app.get("/badge/{owner}/{name}")
    def badge(owner: str, name: str) -> dict[str, Any]:
        """shields.io endpoint badge: https://img.shields.io/endpoint?url=<this URL>"""
        runs = service.store.runs(_repo(owner, name).html_url)
        if not runs:
            return {
                "schemaVersion": 1,
                "label": "DrRepo",
                "message": "not analyzed",
                "color": "lightgrey",
            }
        score = float(runs[-1]["overall_score"])
        letter = grade(score)
        return {
            "schemaVersion": 1,
            "label": "DrRepo",
            "message": f"{score:.0f}/100 ({letter})",
            "color": _BADGE_COLORS.get(letter, "lightgrey"),
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(_who: Client) -> str:
        jobs: dict[Labels, float] = {
            (("status", status),): float(len(queue.store.jobs(statuses=[status], limit=10_000)))
            for status in PENDING
        }
        breaker = service.breaker_state() or {}
        open_breaker: dict[Labels, float] = {(): 1.0 if breaker.get("state") == "open" else 0.0}
        gauges: dict[str, tuple[str, dict[Labels, float]]] = {
            "drrepo_jobs": ("API jobs waiting or running, by status.", jobs),
            "drrepo_llm_breaker_open": ("1 while the LLM circuit breaker is open.", open_breaker),
        }
        return service.metrics.render(gauges)

    return app
