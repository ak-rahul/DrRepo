"""Tests for the security collector (bandit + secret scanner)."""

import json
from unittest.mock import Mock, patch

from src.collectors.security import _scan_secrets, collect_security
from src.models import CollectorStatus


class TestSecretScan:
    def test_detects_aws_key(self, tmp_path):
        (tmp_path / "config.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')

        findings = _scan_secrets(tmp_path)

        assert any(f["type"] == "AWS Access Key" for f in findings)

    def test_ignores_low_entropy_lookalikes(self, tmp_path):
        (tmp_path / "config.py").write_text('password = "aaaaaaaaaaaaaaaaaaaa"\n')

        findings = _scan_secrets(tmp_path)

        assert findings == []

    def test_skips_git_and_node_modules_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')

        findings = _scan_secrets(tmp_path)

        assert findings == []

    def test_clean_repo_has_no_findings(self, tmp_path):
        (tmp_path / "main.py").write_text("def main():\n    return 42\n")

        assert _scan_secrets(tmp_path) == []


class TestCollectSecurity:
    def test_missing_clone_path_is_skipped(self, fake_config, tmp_path):
        result = collect_security(str(tmp_path / "nope"), fake_config)
        assert result.status == CollectorStatus.SKIPPED

    @patch("src.collectors.security.shutil.which", return_value=None)
    def test_bandit_unavailable_falls_back_to_secret_scan_only(
        self, mock_which, fake_config, tmp_path
    ):
        (tmp_path / "main.py").write_text("def f():\n    pass\n")

        result = collect_security(str(tmp_path), fake_config)

        assert result.status == CollectorStatus.OK
        assert "skipped" in result.data["tool_status"]["bandit"]
        assert result.data["tool_status"]["secret_scan"] == "ok"

    @patch("src.collectors.security.shutil.which", return_value="/usr/bin/bandit")
    @patch("src.collectors.security.subprocess.run")
    def test_bandit_findings_are_normalized(self, mock_run, mock_which, fake_config, tmp_path):
        mock_run.return_value = Mock(
            stdout=json.dumps(
                {
                    "results": [
                        {
                            "filename": "app.py",
                            "line_number": 5,
                            "test_id": "B105",
                            "issue_text": "Possible hardcoded password",
                            "issue_severity": "LOW",
                        }
                    ]
                }
            )
        )

        result = collect_security(str(tmp_path), fake_config)

        bandit_findings = [f for f in result.data["findings"] if f["tool"] == "bandit"]
        assert len(bandit_findings) == 1
        assert bandit_findings[0]["rule"] == "B105"

    def test_bandit_disabled_by_config(self, fake_config, tmp_path):
        fake_config.enable_bandit = False

        result = collect_security(str(tmp_path), fake_config)

        assert result.data["tool_status"]["bandit"] == "disabled by config"
