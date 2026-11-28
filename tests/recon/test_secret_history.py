"""Opt-in secret scan over git history: read-only `git log -p`, findings only history holds."""

import shutil
import subprocess
from pathlib import Path

import pytest

from drrepo.config import Config
from drrepo.recon.secret_history import added_secrets, collect_secret_history, git_log_command
from tests.recon.test_scanners import AWS_KEY, GH_TOKEN

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_added_secrets_reads_only_added_lines_with_their_line_numbers():
    stream = [
        "\x00" + "a" * 40 + " 2026-01-02T00:00:00+00:00\n",
        "diff --git a/app.py b/app.py\n",
        "--- a/app.py\n",
        "+++ b/app.py\n",
        "@@ -3,0 +4,2 @@\n",
        "+x = 1\n",
        f'+KEY = "{AWS_KEY}"\n',
        "--- a/old.py\n",
        "+++ /dev/null\n",
        "@@ -1 +0,0 @@\n",
        f'-T = "{GH_TOKEN}"\n',  # removed lines never count
    ]
    assert list(added_secrets(stream)) == [
        {
            "rule": "AWS Access Key",
            "file": "app.py",
            "line": 5,
            "commit": "a" * 40,
            "date": "2026-01-02T00:00:00+00:00",
        }
    ]


def test_git_log_never_runs_diff_drivers():
    cmd = git_log_command(Path(), 5)
    assert {"--no-ext-diff", "--no-textconv", "credential.helper="} <= set(cmd)
    assert cmd[cmd.index("-n") + 1] == "5" and cmd[-1] == "--"


def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


@needs_git
def test_reports_secrets_removed_from_the_tree(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "config.py").write_text(f'AWS = "{AWS_KEY}"\n', encoding="utf-8")
    (root / "app.js").write_text(f"const t = '{GH_TOKEN}';\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add config")
    (root / "config.py").write_text("AWS = os.environ['AWS']\n", encoding="utf-8")
    _git(root, "commit", "-qam", "remove the key")

    # app.js still holds its token, so the tree scanner owns that one.
    present = {("app.js", "GitHub Token")}
    result = collect_secret_history(str(root), Config(scan_history_commits=10), present)
    assert result.status.value == "ok"
    data = result.data
    assert data["commits_scanned"] == 2 and data["truncated"] is False
    [finding] = data["findings"]
    assert (finding["file"], finding["rule"], finding["severity"]) == (
        "config.py",
        "AWS Access Key",
        "HIGH",  # one level below the tree scanner's CRITICAL
    )
    assert finding["tool"] == "secret_history" and finding["line"] == 1
    assert "no longer in the current tree" in finding["message"]
    assert AWS_KEY not in str(data)  # findings never carry the secret itself


def test_off_by_default_and_needs_a_clone(tmp_path):
    off = collect_secret_history(str(tmp_path), Config(), set())
    assert off.status.value == "skipped" and "--scan-history" in off.detail
    missing = collect_secret_history(str(tmp_path), Config(scan_history_commits=5), set())
    assert missing.status.value == "skipped"
