"""Tests for the CLI entry point's helper functions (not the `main()` process wiring)."""

import json

from src.main import print_summary, save_report


def _sample_result():
    return {
        "repository": {"name": "test-repo", "url": "https://github.com/x/y", "stars": 10},
        "overall_score": 75.0,
        "category_scores": {
            "security": {"category": "security", "score": 90.0, "summary": "ok", "issues": []},
        },
        "issues": [
            {
                "severity": "high",
                "category": "security",
                "title": "hardcoded secret",
                "description": "d",
                "recommendation": "remove it",
                "file": "app.py",
                "line": 5,
                "source": "secret_scan",
            }
        ],
        "quick_wins": ["Add a license"],
        "collector_status": {"github_metadata": {"status": "ok", "detail": None}},
    }


class TestPrintSummary:
    def test_runs_without_error_on_full_result(self, capsys):
        print_summary(_sample_result())
        captured = capsys.readouterr()
        assert "test-repo" in captured.out
        assert "hardcoded secret" in captured.out

    def test_runs_without_error_on_empty_result(self, capsys):
        print_summary({})
        captured = capsys.readouterr()
        assert "Unknown" in captured.out


class TestSaveReport:
    def test_saves_json_and_markdown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        json_path = save_report(_sample_result())

        assert json_path.exists()
        md_path = json_path.with_suffix(".md")
        assert md_path.exists()

        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert saved["repository"]["name"] == "test-repo"
        assert "hardcoded secret" in md_path.read_text(encoding="utf-8")
