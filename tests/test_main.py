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

    def test_shows_investigation_trace_for_deep_categories(self, capsys):
        result = _sample_result()
        result["category_scores"]["security"]["investigation_depth"] = "deep"
        result["category_scores"]["security"]["investigation_trace"] = [
            {"tool": "read_file", "tool_input": {"path": "app.py"}, "observation": "..."}
        ]

        print_summary(result)
        captured = capsys.readouterr()

        assert "[investigated]" in captured.out
        assert "How it investigated" in captured.out
        assert "read_file" in captured.out

    def test_no_investigation_section_for_shallow_only_result(self, capsys):
        print_summary(_sample_result())
        captured = capsys.readouterr()

        assert "How it investigated" not in captured.out

    def test_shows_score_delta_when_history_present(self, capsys):
        result = _sample_result()
        result["score_history"] = {
            "previous_timestamp": "2026-07-04T12:00:00+00:00",
            "overall_score_delta": -18.9,
            "category_score_deltas": {"security": -10.0},
        }

        print_summary(result)
        captured = capsys.readouterr()

        assert "-18.9" in captured.out
        assert "down" in captured.out
        assert "2026-07-04" in captured.out

    def test_no_score_delta_line_on_first_ever_run(self, capsys):
        print_summary(_sample_result())
        captured = capsys.readouterr()

        assert "Since last analysis" not in captured.out


class TestSaveReport:
    def test_saves_json_markdown_and_sarif(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        json_path = save_report(_sample_result())

        assert json_path.exists()
        md_path = json_path.with_suffix(".md")
        assert md_path.exists()
        sarif_path = json_path.with_suffix(".sarif")
        assert sarif_path.exists()

        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert saved["repository"]["name"] == "test-repo"
        assert "hardcoded secret" in md_path.read_text(encoding="utf-8")

        sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
        assert sarif["version"] == "2.1.0"
