import pytest

from drrepo.report import history as history


class TestHistory:
    def test_attach_and_record(self, tmp_path, report_dict):
        path = tmp_path / "history.json"
        first = history.attach_and_record_history(dict(report_dict), path)
        assert "score_history" not in first
        second = dict(report_dict, overall_score=report_dict["overall_score"] + 5)
        second = history.attach_and_record_history(second, path)
        assert second["score_history"]["overall_score_delta"] == 5
        assert "code_quality" not in second["score_history"]["category_score_deltas"]  # unassessed
        assert not list(tmp_path.glob("*.tmp"))  # temp files are renamed or removed

    def test_concurrent_writers_lose_no_updates(self, tmp_path, report_dict):
        """Threads in one process and separate processes (the lock file) both serialize."""
        import threading

        path = tmp_path / "h.json"
        threads = [
            threading.Thread(target=history.record_run, args=(dict(report_dict), path))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(history.load_history(path)) == 8

    def test_unwritable_history_does_not_fail_the_run(self, tmp_path, report_dict, monkeypatch):
        def fail(*_args, **_kwargs):
            raise PermissionError("history.json is locked by another program")

        monkeypatch.setattr(history, "record_run", fail)
        report = history.attach_and_record_history(dict(report_dict), tmp_path / "h.json")
        assert report["overall_score"] == report_dict["overall_score"]

    def test_failed_write_leaves_no_temp_file(self, tmp_path, report_dict, monkeypatch):
        path = tmp_path / "h.json"

        def broken_dump(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(history.json, "dump", broken_dump)
        with pytest.raises(OSError, match="disk full"):
            history.record_run(report_dict, path)
        assert not list(tmp_path.glob("*.tmp")) and not path.exists()

    def test_cap_per_repo(self, tmp_path, report_dict, monkeypatch):
        monkeypatch.setattr(history, "_MAX_RUNS_PER_REPO", 3)
        path = tmp_path / "h.json"
        for _ in range(5):
            history.record_run(report_dict, path)
        assert len(history.load_history(path)) == 3

    def test_corrupt_file_is_empty(self, tmp_path):
        path = tmp_path / "h.json"
        path.write_text("{not json", encoding="utf-8")
        assert history.load_history(path) == []


def test_history_records_and_compares_commits(tmp_path, report_dict):
    path = tmp_path / "h.json"
    first = dict(report_dict, repository={**report_dict["repository"], "commit_sha": "1" * 40})
    history.attach_and_record_history(first, path)
    second = dict(report_dict, repository={**report_dict["repository"], "commit_sha": "2" * 40})
    second = history.attach_and_record_history(second, path)
    assert second["score_history"]["previous_commit_sha"] == "1" * 40
    assert [r["commit_sha"] for r in history.load_history(path)] == ["1" * 40, "2" * 40]
