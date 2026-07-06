"""Tests for local score-history tracking (regression detection across runs)."""

import json
import threading

from src.report.history import (
    attach_and_record_history,
    compute_deltas,
    load_history,
    previous_run_for,
    record_run,
)


def _report(name="click", url="https://github.com/pallets/click", overall=80.0, security=90.0):
    return {
        "repository": {"name": name, "url": url},
        "overall_score": overall,
        "category_scores": {
            "security": {"category": "security", "score": security, "summary": "s", "issues": []},
            "documentation": {
                "category": "documentation",
                "score": 70.0,
                "summary": "s",
                "issues": [],
            },
        },
        "issues": [],
        "quick_wins": [],
        "collector_status": {},
    }


class TestLoadHistory:
    def test_missing_file_returns_empty_list(self, tmp_path):
        assert load_history(tmp_path / "nope.json") == []

    def test_corrupt_file_returns_empty_list_not_raise(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert load_history(path) == []

    def test_non_list_json_returns_empty_list(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        assert load_history(path) == []


class TestRecordRun:
    def test_appends_a_record_with_expected_shape(self, tmp_path):
        path = tmp_path / "history.json"
        record_run(_report(), path)

        history = load_history(path)
        assert len(history) == 1
        assert history[0]["repo_key"] == "https://github.com/pallets/click"
        assert history[0]["overall_score"] == 80.0
        assert history[0]["category_scores"]["security"] == 90.0
        assert "timestamp" in history[0]

    def test_caps_history_at_max_runs_per_repo(self, tmp_path):
        path = tmp_path / "history.json"
        for i in range(25):
            record_run(_report(overall=float(i)), path)

        history = load_history(path)
        assert len(history) == 20
        # Oldest runs pruned first, most recent kept.
        assert history[-1]["overall_score"] == 24.0

    def test_different_repos_tracked_independently(self, tmp_path):
        path = tmp_path / "history.json"
        record_run(_report(url="https://github.com/a/a"), path)
        record_run(_report(url="https://github.com/b/b"), path)

        history = load_history(path)
        assert len(history) == 2
        keys = {r["repo_key"] for r in history}
        assert keys == {"https://github.com/a/a", "https://github.com/b/b"}

    def test_concurrent_record_runs_do_not_lose_updates(self, tmp_path):
        """app.py records history from background threads across sessions in
        the same process -- concurrent record_run() calls must not clobber
        each other's read-modify-write of the shared JSON file."""
        path = tmp_path / "history.json"

        def record_one(i):
            record_run(_report(url=f"https://github.com/repo/{i}"), path)

        threads = [threading.Thread(target=record_one, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        history = load_history(path)
        assert len(history) == 30
        keys = {r["repo_key"] for r in history}
        assert keys == {f"https://github.com/repo/{i}" for i in range(30)}


class TestPreviousRunFor:
    def test_returns_none_when_no_history(self):
        assert previous_run_for(_report()["repository"], []) is None

    def test_returns_most_recent_match_for_this_repo(self):
        history = [
            {"repo_key": "https://github.com/pallets/click", "overall_score": 50.0},
            {"repo_key": "https://github.com/other/repo", "overall_score": 99.0},
            {"repo_key": "https://github.com/pallets/click", "overall_score": 70.0},
        ]
        previous = previous_run_for(_report()["repository"], history)
        assert previous["overall_score"] == 70.0


class TestComputeDeltas:
    def test_computes_overall_and_per_category_deltas(self):
        current = _report(overall=63.5, security=50.0)
        previous = {
            "timestamp": "2026-07-04T12:00:00+00:00",
            "overall_score": 82.4,
            "category_scores": {"security": 100.0, "documentation": 70.0},
        }

        deltas = compute_deltas(current, previous)

        assert deltas["overall_score_delta"] == -18.9
        assert deltas["category_score_deltas"]["security"] == -50.0
        assert deltas["category_score_deltas"]["documentation"] == 0.0
        assert deltas["previous_timestamp"] == "2026-07-04T12:00:00+00:00"

    def test_skips_categories_missing_from_previous_run(self):
        current = _report()
        previous = {
            "timestamp": "t",
            "overall_score": 80.0,
            "category_scores": {"security": 90.0},  # no "documentation" entry
        }

        deltas = compute_deltas(current, previous)

        assert "documentation" not in deltas["category_score_deltas"]
        assert "security" in deltas["category_score_deltas"]


class TestAttachAndRecordHistory:
    def test_first_run_has_no_score_history_but_is_recorded(self, tmp_path):
        path = tmp_path / "history.json"
        report = _report()

        result = attach_and_record_history(report, path)

        assert "score_history" not in result
        assert len(load_history(path)) == 1

    def test_second_run_gets_score_history_attached(self, tmp_path):
        path = tmp_path / "history.json"
        attach_and_record_history(_report(overall=80.0), path)

        second = attach_and_record_history(_report(overall=63.5, security=50.0), path)

        assert second["score_history"]["overall_score_delta"] == -16.5
        assert len(load_history(path)) == 2

    def test_result_is_json_serializable_after_attaching_history(self, tmp_path):
        path = tmp_path / "history.json"
        attach_and_record_history(_report(), path)
        second = attach_and_record_history(_report(overall=50.0), path)

        json.dumps(second)  # must not raise
