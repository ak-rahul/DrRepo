"""Local REST API (`drrepo serve`): analyses as background jobs, history, health.

    POST /analyses                     queue an analysis -> 202 {id, status, links}
    GET  /analyses                     recent jobs
    GET  /analyses/{id}                one job: status, progress, summary
    GET  /analyses/{id}/report         the finished report (?format=json|md|sarif|cdx|summary|html)
    GET  /repos/{owner}/{name}/history recorded runs of a repository
    GET  /repos/{owner}/{name}/report  its newest stored report (SQLite store only)
    GET  /health, /health/live, /health/ready   (see interfaces/health.py)

For scripts and tools on this machine. Only local callers are served: a request
from another host, or one carrying proxy headers (`X-Forwarded-For`,
`Forwarded`, `X-Real-IP`), gets 403, so a reverse proxy can't expose the API by
accident. Each analysis can clone a repository and spend LLM tokens, so at most
`API_WORKERS` run at once and `API_MAX_QUEUED` wait (503 beyond that).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from drrepo import __version__
from drrepo.config import Config
from drrepo.jobs import DONE, FAILED, JobQueue, QueueFullError
from drrepo.models import RepoRef
from drrepo.recon.clone import validate_ref
from drrepo.report.exporters import EXPORTERS, FORMATS
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


class AnalysisRequest(BaseModel):
    repo_url: str = Field(description="https://github.com/<owner>/<repo>", max_length=300)
    ref: str | None = Field(default=None, description="branch, tag, or full commit SHA")
    deep: bool | None = Field(
        default=None, description="allow LLM investigations (default: config)"
    )
    description: str = Field(default="", max_length=2000, description="focus for the investigators")


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _LOOPBACK and not any(h in request.headers for h in _PROXY_HEADERS)


def local_only(request: Request) -> None:
    """403 for anything but a direct caller on this machine."""
    if not _is_local(request):
        raise HTTPException(status_code=403, detail="the DrRepo API serves this machine only")


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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        queue.start()
        try:
            yield
        finally:
            queue.shutdown()

    app = FastAPI(
        title="DrRepo API",
        description="Repository audits as background jobs, and score history, on this machine.",
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(local_only)],
    )
    from drrepo.interfaces.health import router as health_router

    app.include_router(health_router)

    def job_or_404(job_id: str) -> dict[str, Any]:
        job = queue.store.job(job_id)
        if job is None:
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
                "GET /health",
            ],
        }

    @app.post("/analyses", status_code=202)
    def submit(body: AnalysisRequest, response: Response) -> dict[str, Any]:
        try:
            repo = RepoRef.parse(body.repo_url)
            ref = validate_ref(body.ref) if body.ref else None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        request = {
            "repo_url": repo.html_url,
            "ref": ref,
            "deep": body.deep,
            "description": body.description,
        }
        try:
            job = queue.submit(request, "local")
        except QueueFullError as e:
            raise HTTPException(
                status_code=503, detail=str(e), headers={"Retry-After": "60"}
            ) from e
        response.headers["Location"] = f"/analyses/{job['id']}"
        return _public_job(job)

    @app.get("/analyses")
    def list_jobs(limit: Annotated[int, Query(ge=1, le=200)] = 20) -> list[Any]:
        return [_public_job(j) for j in queue.store.jobs(limit=limit)]

    @app.get("/analyses/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _public_job(job_or_404(job_id))

    @app.get("/analyses/{job_id}/report")
    def get_report(
        job_id: str,
        format: Annotated[str, Query(pattern="^(" + "|".join(FORMATS) + ")$")] = "json",
    ) -> Response:
        job = job_or_404(job_id)
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
    def history(owner: str, name: str) -> list[dict[str, Any]]:
        return service.store.runs(_repo(owner, name).html_url)

    @app.get("/repos/{owner}/{name}/report")
    def latest(owner: str, name: str) -> dict[str, Any]:
        report = service.store.latest_report(_repo(owner, name).html_url)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="no stored report (full reports are kept with STORE_BACKEND=sqlite)",
            )
        return report

    return app
