"""Tests for the static analysis collector (ruff + semgrep wrappers)."""

import json
import subprocess
from unittest.mock import Mock, patch

from src.collectors.static_analysis import collect_static_analysis
from src.models import CollectorStatus


class TestCollectStaticAnalysis:
    def test_missing_clone_path_is_skipped(self, fake_config, tmp_path):
        result = collect_static_analysis(str(tmp_path / "does_not_exist"), fake_config)
        assert result.status == CollectorStatus.SKIPPED

    @patch("src.collectors.static_analysis.shutil.which", return_value=None)
    def test_no_tools_available_is_skipped(self, mock_which, fake_config, tmp_path):
        result = collect_static_analysis(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.SKIPPED
        assert "ruff" in result.data["tool_status"]

    @patch("src.collectors.static_analysis.shutil.which")
    @patch("src.collectors.static_analysis.subprocess.run")
    def test_ruff_findings_are_normalized(self, mock_run, mock_which, fake_config, tmp_path):
        mock_which.side_effect = lambda tool: "/usr/bin/ruff" if tool == "ruff" else None
        mock_run.return_value = Mock(
            stdout=json.dumps(
                [
                    {
                        "filename": "app.py",
                        "location": {"row": 12},
                        "code": "F401",
                        "message": "'os' imported but unused",
                    }
                ]
            )
        )

        result = collect_static_analysis(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.OK
        assert result.data["tool_status"]["ruff"] == "ok"
        finding = result.data["findings"][0]
        assert finding["tool"] == "ruff"
        assert finding["line"] == 12
        assert finding["rule"] == "F401"

    @patch("src.collectors.static_analysis.shutil.which", return_value="/usr/bin/ruff")
    @patch("src.collectors.static_analysis.subprocess.run")
    def test_ruff_timeout_is_reported_not_raised(self, mock_run, mock_which, fake_config, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ruff", timeout=10)

        result = collect_static_analysis(str(tmp_path), fake_config)

        assert "timed out" in result.data["tool_status"]["ruff"]

    @patch("src.collectors.static_analysis.shutil.which", return_value="/usr/bin/tool")
    @patch("src.collectors.static_analysis.subprocess.run")
    def test_semgrep_disabled_by_config(self, mock_run, mock_which, fake_config, tmp_path):
        fake_config.enable_semgrep = False
        mock_run.return_value = Mock(stdout="[]")

        result = collect_static_analysis(str(tmp_path), fake_config)

        assert result.data["tool_status"]["semgrep"] == "disabled by config"
