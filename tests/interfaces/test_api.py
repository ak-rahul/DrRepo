"""The REST API: background jobs over a store, authentication, limits, history, badges."""

import copy
import threading
import time

import pytest
from fastapi.testclient import TestClient

from drrepo.config import Config
from drrepo.interfaces.api import RateLimiter, create_app
from drrepo.jobs import DONE, FAILED, JobQueue, new_job
from drrepo.report.store import JsonFileStore, SQLiteStore, attach_history
from tests.report.conftest import report_dict  # noqa: F401 - fixture

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.7", 50000)
URL = "https://github.com/octo/demo"


class FakeService:
    """Records each run in the store like AnalysisService does; can block or fail."""

    def __init__(self, store, report, *, fail=None, gate=None):
        self.store, self.report, self.fail, self.gate = store, report, fail, gate
        self.calls = []

    def analyze(self, repo_url, description="", *, deep=None, ref=None, progress=None):
        self.calls.append({"repo_url": repo_url, "ref": ref, "deep": deep})
        if progress:
            progress("Cloning octo/demo")
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise self.fail
        report = copy.deepcopy(self.report)
        report["repository"] = {**report["repository"], "url": repo_url, "name": "octo/demo"}
        return attach_history(report, self.store)


def _client(tmp_path, report, *, client=LOCAL, store=None, service=None, **config):
    store = store or SQLiteStore(tmp_path / "drrepo.db")
    service = service or FakeService(store, report)
    cfg = Config(**{"api_workers": 1, **config})
    queue = JobQueue(service, store, workers=cfg.api_workers, max_queued=cfg.api_max_queued)
    app = create_app(cfg, service=service, queue=queue)  # type: ignore[arg-type]
    return TestClient(app, client=client), service, store


def _wait(api, job_id, headers=None, status=(DONE, FAILED)):
    for _ in range(200):
        job = api.get(f"/analyses/{job_id}", headers=headers or {}).json()
        if job["status"] in status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck at {job['status']}")


def test_an_analysis_runs_as_a_job_and_lands_in_history(tmp_path, report_dict):  # noqa: F811
    api, service, _store = _client(tmp_path, report_dict)
    with api:
        accepted = api.post("/analyses", json={"repo_url": URL, "ref": "v1.0", "deep": False})
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]
        assert accepted.headers["location"] == f"/analyses/{job_id}"
        job = _wait(api, job_id)
        assert job["status"] == DONE and job["summary"]["grade"]
        assert job["progress"] == "Analysis complete" and "report" not in job
        assert service.calls == [{"repo_url": URL, "ref": "v1.0", "deep": False}]

        assert (
            api.get(f"/analyses/{job_id}/report").json()["overall_score"]
            == job["summary"]["overall_score"]
        )
        markdown = api.get(f"/analyses/{job_id}/report", params={"format": "md"})
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert api.get(f"/analyses/{job_id}/report", params={"format": "pdf"}).status_code == 422
        assert [j["id"] for j in api.get("/analyses").json()] == [job_id]

        [run] = api.get("/repos/octo/demo/history").json()
        assert run["repo_key"] == URL
        assert api.get("/repos/octo/demo/report").json()["overall_score"] == run["overall_score"]
        badge = api.get("/badge/octo/demo").json()
        assert badge["schemaVersion"] == 1 and badge["message"].endswith(
            f"({job['summary']['grade']})"
        )
        assert api.get("/badge/octo/other").json()["message"] == "not analyzed"
        assert api.get("/health/live").text == "alive"


def test_without_keys_only_local_clients_are_served(tmp_path, report_dict):  # noqa: F811
    remote, _, _ = _client(tmp_path, report_dict, client=REMOTE)
    with remote:
        assert remote.post("/analyses", json={"repo_url": URL}).status_code == 403
        assert remote.get("/badge/octo/demo").status_code == 200  # badges are public
        assert remote.get("/health/live").status_code == 200
    local, _, _ = _client(tmp_path, report_dict)
    with local:
        # A reverse proxy on this host forwards remote callers: never treated as local.
        proxied = local.post(
            "/analyses", json={"repo_url": URL}, headers={"X-Forwarded-For": "198.51.100.1"}
        )
        assert proxied.status_code == 403


def test_api_keys_authenticate_and_separate_jobs(tmp_path, report_dict):  # noqa: F811
    api, _, store = _client(tmp_path, report_dict, client=REMOTE, api_keys=("alpha", "beta"))
    with api:
        assert api.post("/analyses", json={"repo_url": URL}).status_code == 401
        wrong = api.post("/analyses", json={"repo_url": URL}, headers={"X-API-Key": "nope"})
        assert wrong.status_code == 401
        alpha = {"X-API-Key": "alpha"}
        job_id = api.post("/analyses", json={"repo_url": URL}, headers=alpha).json()["id"]
        _wait(api, job_id, alpha)
        beta = {"Authorization": "Bearer beta"}
        assert api.get(f"/analyses/{job_id}", headers=beta).status_code == 404
        assert api.get("/analyses", headers=beta).json() == []
        assert len(api.get("/analyses", headers=alpha).json()) == 1
    # Jobs record a fingerprint of the key, never the key.
    assert "alpha" not in str(store.job(job_id))


def test_bad_input_rate_limit_and_full_queue(tmp_path, report_dict):  # noqa: F811
    gate = threading.Event()
    store = SQLiteStore(tmp_path / "drrepo.db")
    service = FakeService(store, report_dict, gate=gate)
    api, _, _ = _client(
        tmp_path,
        report_dict,
        store=store,
        service=service,
        api_rate_limit_per_hour=3,
        api_max_queued=1,
    )
    with api:
        assert api.post("/analyses", json={"repo_url": "https://gitlab.com/a/b"}).status_code == 422
        bad_ref = api.post("/analyses", json={"repo_url": URL, "ref": "--upload-pack=x"})
        assert bad_ref.status_code == 422
        first = api.post("/analyses", json={"repo_url": URL}).json()["id"]  # running (blocked)
        _wait(api, first, status=("running",))
        assert api.post("/analyses", json={"repo_url": URL}).status_code == 202  # queued
        full = api.post("/analyses", json={"repo_url": URL})
        assert full.status_code == 503 and full.headers["retry-after"] == "60"
        limited = api.post("/analyses", json={"repo_url": URL})
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
        gate.set()


def test_a_failed_analysis_is_a_failed_job(tmp_path, report_dict):  # noqa: F811
    store = SQLiteStore(tmp_path / "drrepo.db")
    service = FakeService(store, report_dict, fail=ValueError("clone failed"))
    api, _, _ = _client(tmp_path, report_dict, store=store, service=service)
    with api:
        job_id = api.post("/analyses", json={"repo_url": URL}).json()["id"]
        job = _wait(api, job_id)
        assert job["status"] == FAILED and job["error"] == "ValueError: clone failed"
        report = api.get(f"/analyses/{job_id}/report")
        assert report.status_code == 409 and "clone failed" in report.json()["detail"]
        assert api.get("/analyses/does-not-exist").status_code == 404


def test_unfinished_jobs_resume_after_a_restart(tmp_path, report_dict):  # noqa: F811
    store = SQLiteStore(tmp_path / "drrepo.db")
    stale = new_job({"repo_url": URL, "ref": None, "deep": None, "description": ""}, "local")
    store.save_job({**stale, "status": "running"})  # the process died mid-run
    queue = JobQueue(FakeService(store, report_dict), store, workers=1)
    assert queue.start() == 1
    for _ in range(200):
        if store.job(stale["id"])["status"] == DONE:
            break
        time.sleep(0.02)
    queue.shutdown()
    assert store.job(stale["id"])["status"] == DONE


def test_json_store_keeps_jobs_in_memory_and_no_reports(tmp_path, report_dict):  # noqa: F811
    store = JsonFileStore(tmp_path / "history.json")
    api, _, _ = _client(tmp_path, report_dict, store=store)
    with api:
        job_id = api.post("/analyses", json={"repo_url": URL}).json()["id"]
        assert _wait(api, job_id)["status"] == DONE
        assert api.get("/repos/octo/demo/report").status_code == 404
        assert len(api.get("/repos/octo/demo/history").json()) == 1


def test_rate_limiter_slides():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.acquire("a") is None and limiter.acquire("a") is None
    assert limiter.acquire("a") == pytest.approx(3600)
    assert limiter.acquire("b") is None  # per client
    now[0] = 3600.0
    assert limiter.acquire("a") is None


def test_queue_requires_start(tmp_path, report_dict):  # noqa: F811
    store = JsonFileStore(tmp_path / "h.json")
    with pytest.raises(RuntimeError, match="start"):
        JobQueue(FakeService(store, report_dict), store).submit({"repo_url": URL}, "local")


def test_metrics_endpoint(tmp_path, report_dict):  # noqa: F811
    from drrepo.metrics import Metrics

    store = SQLiteStore(tmp_path / "drrepo.db")
    service = FakeService(store, report_dict)
    service.metrics = Metrics()
    service.metrics.inc("drrepo_analyses_total", outcome="ok")
    service.breaker_state = lambda: {"state": "open"}
    api, _, _ = _client(tmp_path, report_dict, store=store, service=service)
    with api:
        text = api.get("/metrics").text
    assert 'drrepo_analyses_total{outcome="ok"} 1' in text
    assert 'drrepo_jobs{status="queued"} 0' in text and "drrepo_llm_breaker_open 1" in text
