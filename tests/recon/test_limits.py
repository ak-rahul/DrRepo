"""Scanner subprocesses run under prlimit caps on Linux, unchanged elsewhere."""

from drrepo.config import Config
from drrepo.recon import limits


def test_caps_are_a_prlimit_prefix(monkeypatch):
    monkeypatch.setattr(limits, "_prlimit", lambda: "/usr/bin/prlimit")
    argv = ["bandit", "-r", "."]
    assert limits.limited(argv, Config()) == [
        "/usr/bin/prlimit",
        f"--fsize={512 * 1024 * 1024}",
        "--",
        *argv,
    ]
    both = limits.limited(argv, Config(scanner_memory_mb=2048, scanner_file_size_mb=64))
    assert both[1:3] == [f"--fsize={64 * 1024 * 1024}", f"--as={2048 * 1024 * 1024}"]
    assert limits.limited(argv, Config(enable_scanner_limits=False)) == argv


def test_without_prlimit_commands_run_unchanged(monkeypatch):
    monkeypatch.setattr(limits, "_prlimit", lambda: None)
    assert limits.limited(["ruff", "check"], Config()) == ["ruff", "check"]


def test_scanners_are_launched_through_the_wrapper(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from drrepo.recon import scanners

    seen = []
    monkeypatch.setattr(limits, "_prlimit", lambda: "/usr/bin/prlimit")
    monkeypatch.setattr(scanners, "find_executable", lambda _t: "/bin/ruff")
    monkeypatch.setattr(
        scanners.subprocess,
        "run",
        lambda argv, **_k: seen.append(argv) or SimpleNamespace(stdout="[]", returncode=0),
    )
    scanners.run_ruff(tmp_path, config=Config(scanner_file_size_mb=1))
    assert seen[0][:3] == ["/usr/bin/prlimit", f"--fsize={1024 * 1024}", "--"]
