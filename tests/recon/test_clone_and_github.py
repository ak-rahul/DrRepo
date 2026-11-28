import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from github import GithubException

from drrepo.config import Config
from drrepo.recon import clone, github
from drrepo.recon.clone import clone_repo
from drrepo.recon.github import collect_github_metadata


class TestClone:
    def test_rejects_non_github_url(self, config):
        cloned, result = clone_repo("https://gitlab.com/a/b", config)
        assert cloned is None and result.status.value == "error"

    @staticmethod
    def _fake_git(monkeypatch, sha="a" * 40):
        calls: list[dict[str, object]] = []

        def fake_run(cmd, **kwargs):
            calls.append({"cmd": cmd, **kwargs})
            stdout = sha + "\n" if "rev-parse" in cmd else ""
            return SimpleNamespace(returncode=0, stderr="", stdout=stdout)

        monkeypatch.setattr(clone.shutil, "which", lambda _n: "/usr/bin/git")
        monkeypatch.setattr(clone.subprocess, "run", fake_run)
        return calls

    def test_hardened_command_records_commit_and_cleans_up(self, config, monkeypatch):
        calls = self._fake_git(monkeypatch)
        cloned, result = clone_repo("https://github.com/octo/demo/tree/main", config)
        try:
            assert result.status.value == "ok"
            assert result.data["commit_sha"] == "a" * 40 and result.data["ref"] is None
            cmd = calls[0]["cmd"]
            assert "clone" in cmd
            assert cmd[-2] == "https://github.com/octo/demo.git"  # normalized, after "--"
            assert cmd[-3] == "--"
            assert "core.symlinks=false" in cmd and "credential.helper=" in cmd
            assert calls[0]["env"]["GIT_TERMINAL_PROMPT"] == "0"
            assert calls[0]["stdin"] is subprocess.DEVNULL
            assert "rev-parse" in calls[-1]["cmd"]
        finally:
            assert cloned is not None
            cloned.cleanup()
        assert not cloned.path.exists()

    def test_ref_uses_shallow_fetch_after_double_dash(self, config, monkeypatch):
        calls = self._fake_git(monkeypatch)
        cloned, result = clone_repo("https://github.com/octo/demo", config, ref="v1.2.0")
        assert cloned is not None
        cloned.cleanup()
        assert result.data["ref"] == "v1.2.0"
        fetch = next(c["cmd"] for c in calls if "fetch" in c["cmd"])
        assert fetch[-2:] == ["--", "v1.2.0"] and "--depth" in fetch
        assert "core.symlinks=false" in next(c["cmd"] for c in calls if "checkout" in c["cmd"])

    def test_history_scan_deepens_the_clone(self, monkeypatch):
        import dataclasses

        from drrepo.config import Config

        calls = self._fake_git(monkeypatch)
        config = dataclasses.replace(Config(), scan_history_commits=5)
        cloned, _ = clone_repo("https://github.com/octo/demo", config)
        assert cloned is not None
        cloned.cleanup()
        cmd = calls[0]["cmd"]
        assert cmd[cmd.index("--depth") + 1] == "6"  # N+1: the oldest scanned commit has a parent

    @pytest.mark.parametrize(
        "bad", ["--upload-pack=x", "a..b", "x@{1}", "-x", "a b", "a.lock", "a/", ""]
    )
    def test_unsafe_refs_never_reach_git(self, config, monkeypatch, bad):
        calls = self._fake_git(monkeypatch)
        cloned, result = clone_repo("https://github.com/octo/demo", config, ref=bad)
        assert cloned is None and result.status.value == "error" and calls == []

    def test_abbreviated_sha_gets_a_precise_hint(self, config, monkeypatch):
        monkeypatch.setattr(clone.shutil, "which", lambda _n: "git")
        monkeypatch.setattr(
            clone.subprocess,
            "run",
            lambda cmd, **_k: SimpleNamespace(
                returncode=128 if "fetch" in cmd else 0,
                stderr="fatal: couldn't find remote ref abc1234",
                stdout="",
            ),
        )
        _, result = clone_repo("https://github.com/octo/demo", config, ref="abc1234")
        assert "full 40-character SHA" in result.detail

    def test_failure_cleans_up_and_hints_private(self, config, monkeypatch):
        created = []
        real_mkdtemp = clone.tempfile.mkdtemp

        def mkdtemp(**kw):
            path = real_mkdtemp(**kw)
            created.append(path)
            return path

        monkeypatch.setattr(clone.tempfile, "mkdtemp", mkdtemp)
        monkeypatch.setattr(clone.shutil, "which", lambda _n: "git")
        monkeypatch.setattr(
            clone.subprocess,
            "run",
            lambda *_a, **_k: SimpleNamespace(
                returncode=128, stderr="fatal: could not read Username", stdout=""
            ),
        )
        cloned, result = clone_repo("https://github.com/octo/private", config)
        assert cloned is None
        assert "private or does not exist" in result.detail
        assert not any(__import__("os").path.exists(p) for p in created)

    def test_timeout(self, config, monkeypatch):
        monkeypatch.setattr(clone.shutil, "which", lambda _n: "git")

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired("git", 1)

        monkeypatch.setattr(clone.subprocess, "run", boom)
        assert "timed out" in clone_repo("https://github.com/a/b", config)[1].detail

    def test_size_cap(self, monkeypatch):
        monkeypatch.setattr(clone.shutil, "which", lambda _n: "git")
        monkeypatch.setattr(
            clone.subprocess,
            "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stderr="", stdout="f" * 40),
        )
        monkeypatch.setattr(clone, "_dir_size_mb", lambda _p: 999.0)
        cloned, result = clone_repo("https://github.com/a/b", Config(clone_max_size_mb=10))
        assert cloned is None and result.status.value == "skipped" and "999MB" in result.detail

    def test_git_missing(self, config, monkeypatch):
        monkeypatch.setattr(clone.shutil, "which", lambda _n: None)
        assert clone_repo("https://github.com/a/b", config)[1].status.value == "skipped"


def _fake_repo(**overrides):
    when = datetime(2026, 1, 1, tzinfo=UTC)
    repo = MagicMock()
    repo.name, repo.full_name, repo.description = "demo", "octo/demo", None
    repo.html_url = "https://github.com/octo/demo"
    repo.stargazers_count, repo.forks_count, repo.subscribers_count = 10, 2, 3
    repo.language, repo.size, repo.default_branch, repo.open_issues_count = None, 100, "main", 4
    repo.archived = False
    repo.license = SimpleNamespace(name="MIT License", spdx_id="MIT")
    repo.created_at = repo.updated_at = repo.pushed_at = when
    repo.get_topics.return_value = ["x"]
    repo.get_readme.return_value = SimpleNamespace(decoded_content=b"# Demo")
    repo.get_contents.return_value = [
        SimpleNamespace(name=n) for n in ("tests", ".github", "LICENSE", "CHANGELOG.md")
    ]
    for k, v in overrides.items():
        setattr(repo, k, v)
    return repo


class TestGithub:
    def test_collects_metadata(self, config, monkeypatch):
        client = MagicMock()
        client.get_repo.return_value = _fake_repo()
        monkeypatch.setattr(github, "make_github_client", lambda _t: client)
        result = collect_github_metadata("https://github.com/octo/demo.git", config)
        client.get_repo.assert_called_once_with("octo/demo")
        data = result.data
        assert data["language"] == "Unknown" and data["description"] == ""
        assert data["license_spdx_id"] == "MIT" and data["readme_content"] == "# Demo"
        assert data["file_structure"] == {
            "has_tests": True,
            "has_ci": True,
            "has_docs": False,
            "has_license": True,
            "has_contributing": False,
            "has_changelog": True,
        }

    def test_missing_readme_and_empty_repo(self, config, monkeypatch):
        repo = _fake_repo()
        repo.get_readme.side_effect = GithubException(404, {}, None)
        repo.get_contents.side_effect = GithubException(404, {}, None)
        client = MagicMock(get_repo=MagicMock(return_value=repo))
        monkeypatch.setattr(github, "make_github_client", lambda _t: client)
        data = collect_github_metadata("https://github.com/octo/demo", config).data
        assert data["readme_content"] == "" and not any(data["file_structure"].values())

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [(404, "not found"), (403, "rate limit"), (401, "rejected"), (500, "status 500")],
    )
    def test_api_errors(self, config, monkeypatch, status, fragment):
        client = MagicMock()
        client.get_repo.side_effect = GithubException(status, {}, None)
        monkeypatch.setattr(github, "make_github_client", lambda _t: client)
        result = collect_github_metadata("https://github.com/octo/demo", config)
        assert result.status.value == "error" and fragment in result.detail

    def test_invalid_url(self, config):
        assert collect_github_metadata("nope", config).status.value == "error"
