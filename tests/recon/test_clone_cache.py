"""Clones reused by commit: ls-remote resolution, copy-out hits, TTL and size eviction."""

import dataclasses
import os
import time
from types import SimpleNamespace

from drrepo.config import Config
from drrepo.recon import clone, clone_cache
from drrepo.recon.clone_cache import CloneCache, resolve_commit

SHA = "c" * 40
TAG_OBJECT = "d" * 40


def _ls_remote(monkeypatch, stdout, returncode=0):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(clone_cache.subprocess, "run", fake_run)
    return calls


def test_resolve_commit_peels_tags_and_reads_head(monkeypatch):
    calls = _ls_remote(
        monkeypatch,
        f"{TAG_OBJECT}\trefs/tags/v1.0\n{SHA}\trefs/tags/v1.0^{{}}\n{'e' * 40}\tHEAD\n",
    )
    assert resolve_commit("https://github.com/o/r.git", "v1.0", 5) == SHA  # the commit, not the tag
    assert resolve_commit("https://github.com/o/r.git", None, 5) == "e" * 40
    assert calls[0][-3:] == ["--", "https://github.com/o/r.git", "v1.0"]
    assert resolve_commit("u", "f" * 40, 5) == "f" * 40 and len(calls) == 2  # a SHA needs no call
    _ls_remote(monkeypatch, "", returncode=128)
    assert resolve_commit("u", "main", 5) is None


def test_store_then_checkout_copies_and_leaves_the_cache_intact(tmp_path):
    cache = CloneCache(tmp_path / "cache", ttl_seconds=600, max_mb=100)
    source = tmp_path / "clone"
    (source / ".git").mkdir(parents=True)
    (source / "app.py").write_text("x = 1\n", encoding="utf-8")
    cache.store("Octo/Demo", SHA, 1, source)
    first, second = tmp_path / "run1", tmp_path / "run2"
    assert cache.checkout("octo/demo", SHA, 1, first)
    clone.remove_tree(first)  # what a run's cleanup does
    assert cache.checkout("octo/demo", SHA, 1, second)
    assert (second / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not cache.checkout("octo/demo", SHA, 21, tmp_path / "deeper")  # depth is in the key


def test_expired_and_oversized_entries_are_evicted(tmp_path):
    cache = CloneCache(tmp_path / "cache", ttl_seconds=60, max_mb=100)
    source = tmp_path / "clone"
    source.mkdir()
    (source / "f").write_bytes(b"x" * 1024)
    cache.store("o/old", SHA, 1, source)
    old = next((tmp_path / "cache").iterdir())
    past = time.time() - 120
    os.utime(old, (past, past))
    assert not cache.checkout("o/old", SHA, 1, tmp_path / "gone")
    assert not old.exists()

    tiny = CloneCache(tmp_path / "small", ttl_seconds=600, max_mb=0.0015)  # room for one entry
    tiny.store("o/a", SHA, 1, source)
    tiny.store("o/b", SHA, 1, source)
    assert [p.name.split("@")[0] for p in (tmp_path / "small").iterdir()] == ["o_b"]


def test_clone_repo_uses_the_cache_when_enabled(tmp_path, monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        if "ls-remote" in cmd:
            return SimpleNamespace(returncode=0, stdout=f"{SHA}\tHEAD\n", stderr="")
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout=SHA + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(clone.shutil, "which", lambda _n: "/usr/bin/git")
    monkeypatch.setattr(clone.subprocess, "run", fake_run)
    monkeypatch.setattr(clone_cache.subprocess, "run", fake_run)
    config = dataclasses.replace(
        Config(), clone_cache_ttl_seconds=600, clone_cache_dir=str(tmp_path / "cache")
    )
    first, result = clone.clone_repo("https://github.com/octo/demo", config)
    assert first is not None and "cached" not in result.data
    first.cleanup()
    clones = sum("clone" in cmd for cmd in runs)
    second, result = clone.clone_repo("https://github.com/octo/demo", config)
    assert second is not None and result.data["cached"] is True
    assert result.data["commit_sha"] == SHA
    assert sum("clone" in cmd for cmd in runs) == clones  # no second git clone
    second.cleanup()
    before = len(runs)
    off, _ = clone.clone_repo("https://github.com/octo/demo", Config())
    assert off is not None
    off.cleanup()
    assert not any("ls-remote" in cmd for cmd in runs[before:])  # off by default: no lookup
