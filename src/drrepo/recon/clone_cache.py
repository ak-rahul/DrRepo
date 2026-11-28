"""A short-lived cache of clones by commit, so repeat runs and diff mode don't clone twice.

Off by default (`CLONE_CACHE_TTL_SECONDS=0`); worth it for long-running servers
(`drrepo serve`, the web UI) and for `drrepo diff --deep`, which analyzes the
head commit twice. A clone is keyed by repository, commit SHA and depth (a
history scan fetches more commits). Before cloning, `resolve_commit` asks the
remote which commit a ref names (`git ls-remote`, nothing downloaded); a hit is
copied out of the cache, so the caller's cleanup never touches the cache.

Entries older than the TTL are deleted, and the oldest go first when the cache
outgrows `CLONE_CACHE_MAX_MB`. A failure anywhere here only means a fresh
clone: the cache never fails an analysis.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from drrepo.config import Config
from drrepo.log import logger
from drrepo.recon.files import dir_size_mb, remove_tree

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_lock = threading.Lock()


def default_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "drrepo-clone-cache"


def resolve_commit(clone_url: str, ref: str | None, timeout: float) -> str | None:
    """The full SHA `ref` (or the default branch) names on the remote, or None.

    A full SHA is returned as is. An annotated tag resolves to its commit (the
    peeled `^{}` line). Anything ambiguous or unreachable returns None.
    """
    if ref is not None and _FULL_SHA.match(ref):
        return ref
    from drrepo.recon.clone import git_env  # clone imports this module

    pattern = ref or "HEAD"
    try:
        result = subprocess.run(
            ["git", "-c", "credential.helper=", "ls-remote", "--", clone_url, pattern],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=git_env(),
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if _FULL_SHA.match(sha):
            refs[name] = sha
    if ref is None:
        return refs.get("HEAD")
    for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}", ref):
        if name in refs:
            return refs[name]
    return None


class CloneCache:
    def __init__(self, root: Path, ttl_seconds: float, max_mb: float) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.max_mb = max_mb

    @classmethod
    def from_config(cls, config: Config) -> CloneCache | None:
        if config.clone_cache_ttl_seconds <= 0:
            return None
        root = Path(config.clone_cache_dir) if config.clone_cache_dir else default_cache_dir()
        return cls(root, config.clone_cache_ttl_seconds, config.clone_cache_max_mb)

    def _entry(self, full_name: str, sha: str, depth: int) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", full_name.lower())
        return self.root / f"{safe}@{sha}-d{depth}"

    def checkout(self, full_name: str, sha: str, depth: int, dest: Path) -> bool:
        """Copy a fresh cached clone into `dest` (which must not exist). True on a hit."""
        entry = self._entry(full_name, sha, depth)
        with _lock:
            self._evict()
            if not entry.is_dir():
                return False
            try:
                shutil.copytree(entry, dest, symlinks=True)
            except OSError as e:
                logger.warning(f"Clone cache read failed for {entry.name}: {e}")
                remove_tree(dest)
                return False
        logger.info(f"Clone cache hit: {full_name}@{sha[:12]}")
        return True

    def store(self, full_name: str, sha: str, depth: int, source: Path) -> None:
        """Keep a copy of a finished clone (`source` stays the caller's)."""
        entry = self._entry(full_name, sha, depth)
        with _lock:
            if entry.exists():
                return
            staging = entry.with_name(entry.name + f".tmp{os.getpid()}")
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, staging, symlinks=True)
                staging.replace(entry)
                os.utime(entry)  # copytree copies the clone's mtime; the TTL counts from now
            except OSError as e:
                logger.warning(f"Clone cache write failed for {entry.name}: {e}")
                remove_tree(staging)
                return
            self._evict(keep=entry)

    def _evict(self, keep: Path | None = None) -> None:
        """Delete expired entries, then the oldest while the cache is over its size cap.
        `keep` (the entry just stored) is never the one evicted."""
        if not self.root.is_dir():
            return
        now = time.time()
        entries = []
        for path in self.root.iterdir():
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age > self.ttl_seconds or (".tmp" in path.name and age > 3600):
                remove_tree(path)
            elif path.is_dir() and ".tmp" not in path.name and path != keep:
                entries.append((age, path))
        sizes = {path: dir_size_mb(path) for _age, path in entries}
        total = sum(sizes.values()) + (dir_size_mb(keep) if keep is not None else 0.0)
        for _age, path in sorted(entries, reverse=True):  # oldest first
            if total <= self.max_mb:
                break
            remove_tree(path)
            total -= sizes[path]
