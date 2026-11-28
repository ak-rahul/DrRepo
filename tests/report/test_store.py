"""Both stores behind one protocol: runs, full reports (SQLite), jobs."""

import sqlite3
import threading

import pytest

from drrepo.config import Config
from drrepo.errors import ConfigurationError
from drrepo.report.history import repo_key
from drrepo.report.store import JsonFileStore, SQLiteStore, attach_history, open_store


@pytest.fixture(params=["json", "sqlite"])
def store(request, tmp_path):
    if request.param == "json":
        return JsonFileStore(tmp_path / "history.json")
    return SQLiteStore(tmp_path / "drrepo.db")


def _report(report_dict, score, sha="a" * 40):
    return dict(
        report_dict,
        overall_score=score,
        repository={**report_dict["repository"], "commit_sha": sha},
    )


def test_runs_are_recorded_per_repository_oldest_first(store, report_dict):
    key = repo_key(report_dict["repository"])
    attach_history(_report(report_dict, 60.0, "1" * 40), store)
    second = attach_history(_report(report_dict, 70.0, "2" * 40), store)
    assert second["score_history"]["overall_score_delta"] == 10.0
    assert [r["commit_sha"] for r in store.runs(key)] == ["1" * 40, "2" * 40]
    assert store.runs("https://github.com/other/repo") == []
    assert len(store.runs()) == 2


def test_only_sqlite_keeps_full_reports(tmp_path, report_dict):
    key = repo_key(report_dict["repository"])
    sqlite_store = SQLiteStore(tmp_path / "drrepo.db")
    sqlite_store.record(_report(report_dict, 61.5))
    assert sqlite_store.latest_report(key)["overall_score"] == 61.5
    assert sqlite_store.runs(key)[0]["run_id"] == 1
    assert JsonFileStore(tmp_path / "h.json").latest_report(key) is None


def test_jobs_round_trip_newest_first(store):
    for n, status in enumerate(["done", "queued", "running"]):
        store.save_job(
            {
                "id": f"job-{n}",
                "status": status,
                "request": {"repo_url": "https://github.com/a/b"},
                "client": "local",
                "created_at": f"2026-11-28T00:00:0{n}+00:00",
                "report": {"overall_score": 1.0} if status == "done" else None,
            }
        )
    assert store.job("job-0")["report"] == {"overall_score": 1.0}
    assert store.job("job-0")["request"]["repo_url"] == "https://github.com/a/b"
    assert [j["id"] for j in store.jobs()] == ["job-2", "job-1", "job-0"]
    assert [j["id"] for j in store.jobs(statuses=["queued", "running"])] == ["job-2", "job-1"]
    assert store.job("missing") is None
    store.save_job({**store.job("job-1"), "status": "done"})
    assert store.job("job-1")["status"] == "done"


def test_sqlite_caps_runs_per_repository_and_survives_concurrent_writers(tmp_path, report_dict):
    store = SQLiteStore(tmp_path / "drrepo.db", max_runs_per_repo=5)
    threads = [
        threading.Thread(target=store.record, args=(_report(report_dict, float(i)),))
        for i in range(12)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.runs(repo_key(report_dict["repository"]))) == 5
    # A second handle on the same file sees the same data (another process, a restart).
    assert len(SQLiteStore(tmp_path / "drrepo.db").runs()) == 5


def test_a_failing_store_never_fails_the_report(report_dict):
    class Broken:
        def runs(self, repo=None):
            raise sqlite3.OperationalError("database is locked")

        def record(self, report):
            raise sqlite3.OperationalError("database is locked")

    report = attach_history(_report(report_dict, 50.0), Broken())  # type: ignore[arg-type]
    assert report["overall_score"] == 50.0 and "score_history" not in report


def test_open_store_follows_the_config(tmp_path):
    assert isinstance(open_store(Config()), JsonFileStore)
    chosen = open_store(Config(store_backend="sqlite", store_path=str(tmp_path / "x.db")))
    assert isinstance(chosen, SQLiteStore) and chosen.path == tmp_path / "x.db"
    with pytest.raises(ConfigurationError, match="STORE_BACKEND"):
        Config(store_backend="postgres")
