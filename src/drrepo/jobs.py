"""Background analysis jobs: a bounded worker pool whose state lives in a `ReportStore`.

The REST API (`interfaces/api.py`) submits a job and returns at once; a worker
runs `AnalysisService.analyze` and writes the job's progress, summary and
report back to the store. With the SQLite store, jobs survive a restart:
`start()` re-queues whatever was queued or running when the process stopped.

A job is a plain dict (see `new_job`) so every store can keep it as is:
    id, status ("queued" | "running" | "done" | "failed"), request, client,
    created_at, started_at, finished_at, progress (last message), error,
    summary ({overall_score, grade, issue_counts, commit_sha}), report.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from drrepo.log import logger
from drrepo.report.synthesis import grade

if TYPE_CHECKING:
    from drrepo.report.store import ReportStore
    from drrepo.service import AnalysisService

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
PENDING = (QUEUED, RUNNING)


class QueueFullError(Exception):
    """More jobs are waiting than `max_queued` allows."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_job(request: dict[str, Any], client: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "status": QUEUED,
        "request": request,
        "client": client,
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "progress": None,
        "error": None,
        "summary": None,
        "report": None,
    }


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    score = float(report.get("overall_score", 0.0))
    return {
        "overall_score": score,
        "grade": grade(score),
        "issue_counts": report.get("issue_counts"),
        "commit_sha": (report.get("repository") or {}).get("commit_sha"),
    }


class JobQueue:
    """Runs submitted analyses on `workers` threads, at most `max_queued` waiting."""

    def __init__(
        self,
        service: AnalysisService,
        store: ReportStore,
        *,
        workers: int = 2,
        max_queued: int = 50,
    ) -> None:
        self.service = service
        self.store = store
        self.workers = workers
        self.max_queued = max_queued
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def start(self) -> int:
        """Start the workers and re-queue unfinished jobs. Returns how many were re-queued."""
        self._executor = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="drrepo-job"
        )
        unfinished = sorted(self.store.jobs(statuses=PENDING, limit=10_000), key=_created)
        for job in unfinished:
            job.update(status=QUEUED, started_at=None, progress="re-queued after a restart")
            self.store.save_job(job)
            self._executor.submit(self._run, job["id"])
        if unfinished:
            logger.info(f"Re-queued {len(unfinished)} unfinished job(s)")
        return len(unfinished)

    def shutdown(self) -> None:
        """Stop taking work. Running jobs finish; queued ones stay queued for the next start."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def submit(self, request: dict[str, Any], client: str) -> dict[str, Any]:
        """Queue an analysis. Raises QueueFullError when `max_queued` jobs are waiting."""
        if self._executor is None:
            raise RuntimeError("JobQueue.start() was not called")
        with self._lock:
            if len(self.store.jobs(statuses=[QUEUED], limit=self.max_queued + 1)) >= (
                self.max_queued
            ):
                raise QueueFullError(f"{self.max_queued} analyses are already waiting")
            job = new_job(request, client)
            self.store.save_job(job)
        self._executor.submit(self._run, job["id"])
        return job

    def _run(self, job_id: str) -> None:
        job = self.store.job(job_id)
        if job is None or job["status"] != QUEUED:
            return
        job.update(status=RUNNING, started_at=_now())
        self.store.save_job(job)
        save_lock = threading.Lock()

        def progress(message: str) -> None:
            with save_lock:  # LangGraph reports from worker threads
                job["progress"] = message
                self.store.save_job(job)

        request = job["request"]
        try:
            report = self.service.analyze(
                request["repo_url"],
                request.get("description") or "",
                deep=request.get("deep"),
                ref=request.get("ref"),
                progress=progress,
            )
        except Exception as e:  # a failed analysis is a failed job, never a dead worker
            logger.warning(f"Job {job_id} failed: {type(e).__name__}: {e}")
            with save_lock:
                job.update(status=FAILED, finished_at=_now(), error=f"{type(e).__name__}: {e}")
                self.store.save_job(job)
            return
        with save_lock:
            job.update(
                status=DONE,
                finished_at=_now(),
                summary=summarize(report),
                report=report,
                progress="Analysis complete",
            )
            self.store.save_job(job)


def _created(job: dict[str, Any]) -> str:
    return str(job.get("created_at") or "")
