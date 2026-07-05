"""Tests for the on-demand narrow scanner tool."""

from unittest.mock import Mock, patch

from src.tools.scan_tools import make_scan_tools


class TestRunScannerOnPath:
    def test_unknown_scanner_returns_error(self, fake_config, tmp_path):
        (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)

        result = run_scanner.invoke({"scanner": "eslint", "path": "."})

        assert result.startswith("ERROR: unknown scanner")

    def test_path_traversal_returns_error(self, fake_config, tmp_path):
        (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)

        result = run_scanner.invoke({"scanner": "ruff", "path": "../../../etc"})

        assert "escapes the repository root" in result

    def test_nonexistent_path_returns_error(self, fake_config, tmp_path):
        (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)

        result = run_scanner.invoke({"scanner": "ruff", "path": "nope.py"})

        assert result.startswith("ERROR")

    def test_no_findings_message(self, fake_config, tmp_path):
        (tmp_path / "clean.py").write_text("x = 1\n")
        mock_run_ruff = Mock(return_value={"available": True, "findings": []})

        # `_SCANNERS` binds function references at import time, so
        # `patch("...._run_ruff")` alone would never be seen by the dict
        # lookup -- patch.dict overrides the dict entry itself instead.
        with patch.dict("src.tools.scan_tools._SCANNERS", {"ruff": mock_run_ruff}):
            (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)
            result = run_scanner.invoke({"scanner": "ruff", "path": "clean.py"})

        mock_run_ruff.assert_called_once()
        assert "no issues" in result

    def test_findings_are_returned(self, fake_config, tmp_path):
        (tmp_path / "app.py").write_text("import os\n")
        mock_run_ruff = Mock(
            return_value={
                "available": True,
                "findings": [{"code": "F401", "message": "unused import"}],
            }
        )

        with patch.dict("src.tools.scan_tools._SCANNERS", {"ruff": mock_run_ruff}):
            (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)
            result = run_scanner.invoke({"scanner": "ruff", "path": "app.py"})

        assert "F401" in result

    def test_bandit_uses_results_key(self, fake_config, tmp_path):
        (tmp_path / "app.py").write_text("import os\n")
        mock_run_bandit = Mock(
            return_value={
                "available": True,
                "results": [{"test_id": "B105", "issue_text": "hardcoded password"}],
            }
        )

        with patch.dict("src.tools.scan_tools._SCANNERS", {"bandit": mock_run_bandit}):
            (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)
            result = run_scanner.invoke({"scanner": "bandit", "path": "app.py"})

        assert "B105" in result

    def test_unavailable_tool_reports_reason(self, fake_config, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        mock_run_semgrep = Mock(
            return_value={"available": False, "reason": "semgrep not installed"}
        )

        with patch.dict("src.tools.scan_tools._SCANNERS", {"semgrep": mock_run_semgrep}):
            (run_scanner,) = make_scan_tools(str(tmp_path), fake_config)
            result = run_scanner.invoke({"scanner": "semgrep", "path": "app.py"})

        assert "unavailable" in result
