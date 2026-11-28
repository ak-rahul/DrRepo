import time
from unittest.mock import MagicMock

import pytest

from drrepo.agents import tools as tools_module
from drrepo.agents.tools import (
    PathEscapesSandboxError,
    build_tools,
    make_file_tools,
    make_scan_tools,
    resolve_safe_path,
)
from drrepo.config import Config
from drrepo.recon.scanners import ScanResult


@pytest.fixture
def repo(make_repo):
    return make_repo(
        {
            "src/app.py": "import os\n\ndef main():\n    os.system('ls')\n",
            "src/util.py": "def helper():\n    return 1\n",
            "docs/guide.md": "# Guide\n",
            "node_modules/x/index.js": "os.system",
            "blob.bin": b"\x00\x01",
        }
    )


@pytest.fixture
def tools(repo):
    return {t.name: t for t in make_file_tools(str(repo))}


class TestSandbox:
    @pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "src/../../x", "a\x00b"])
    def test_escapes_rejected(self, repo, bad):
        with pytest.raises(PathEscapesSandboxError):
            resolve_safe_path(repo, bad)

    def test_inside_ok(self, repo):
        assert resolve_safe_path(repo, "src/app.py") == (repo / "src" / "app.py").resolve()
        assert resolve_safe_path(repo, ".") == repo.resolve()


class TestFileTools:
    def test_read_file_numbered_and_ranged(self, tools):
        out = tools["read_file"].invoke({"path": "src/app.py", "start_line": 3, "end_line": 4})
        assert out.splitlines() == ["    3| def main():", "    4|     os.system('ls')"]

    def test_read_file_errors(self, tools):
        assert tools["read_file"].invoke({"path": "../x"}).startswith("ERROR")
        assert "not a file" in tools["read_file"].invoke({"path": "src"})
        assert "binary" in tools["read_file"].invoke({"path": "blob.bin"})

    def test_list_directory(self, tools):
        out = tools["list_directory"].invoke({"path": "."})
        assert "dir   src/" in out and "node_modules/  (vendored" in out
        assert "escapes" in tools["list_directory"].invoke({"path": ".."})

    def test_find_files(self, tools):
        assert tools["find_files"].invoke({"glob": "*.py"}).splitlines() == [
            "src/app.py",
            "src/util.py",
        ]
        assert tools["find_files"].invoke({"glob": "docs/*"}) == "docs/guide.md"
        assert tools["find_files"].invoke({"glob": "../*"}).startswith("ERROR")

    def test_search_code_skips_vendored_and_filters(self, tools):
        out = tools["search_code"].invoke({"pattern": r"os\.system"})
        assert out == "src/app.py:4: os.system('ls')"
        assert (
            tools["search_code"]
            .invoke({"pattern": "HELPER", "ignore_case": True, "glob": "util.py"})
            .startswith("src/util.py:1")
        )
        assert "invalid regex" in tools["search_code"].invoke({"pattern": "("})
        assert "longer than" in tools["search_code"].invoke({"pattern": "a" * 400})

    def test_search_code_survives_catastrophic_backtracking(self, make_repo):
        """An LLM-chosen ReDoS pattern must fail fast, not pin a thread forever."""
        root = make_repo({"bomb.txt": "a" * 60 + "b\n"})
        search = {t.name: t for t in make_file_tools(str(root))}["search_code"]
        started = time.monotonic()
        out = search.invoke({"pattern": r"(a|aa)+$"})
        assert "too slow" in out
        assert time.monotonic() - started < 5

    def test_search_code_stops_at_time_budget(self, repo, monkeypatch):
        monkeypatch.setattr(tools_module, "SEARCH_TIME_BUDGET_SECONDS", -1.0)
        search = {t.name: t for t in make_file_tools(str(repo))}["search_code"]
        assert "time budget" in search.invoke({"pattern": "def"})


class TestScanTool:
    def test_runs_scanner_on_subpath(self, repo, monkeypatch):
        calls = []

        def fake(root, target, timeout, config=None):
            calls.append((root, target))
            return ScanResult(
                "ruff",
                True,
                [
                    {
                        "file": "src/app.py",
                        "line": 4,
                        "rule": "S605",
                        "message": "shell",
                        "severity": None,
                    }
                ],
            )

        monkeypatch.setitem(tools_module.SCANNERS, "ruff", fake)
        [tool] = make_scan_tools(str(repo), Config())
        out = tool.invoke({"scanner": "ruff", "path": "src"})
        assert out == "src/app.py:4: [-] S605: shell"
        assert calls[0][1] == (repo / "src").resolve()

    def test_validation(self, repo):
        [tool] = make_scan_tools(str(repo), Config(enable_semgrep=False))
        assert "unknown scanner" in tool.invoke({"scanner": "eslint"})
        assert "disabled" in tool.invoke({"scanner": "semgrep"})
        assert "escapes" in tool.invoke({"scanner": "ruff", "path": "../.."})
        assert "does not exist" in tool.invoke({"scanner": "ruff", "path": "nope"})


class TestDependencyTool:
    def test_formats_results(self, monkeypatch):
        monkeypatch.setattr(
            tools_module, "query_osv_ids", lambda client, pkgs, cache: {pkgs[0]: ["GHSA-1"]}
        )
        monkeypatch.setattr(
            tools_module,
            "build_vulnerabilities",
            lambda client, ids, cache: [
                {
                    "vuln_id": "GHSA-1",
                    "severity": "high",
                    "summary": "bad",
                    "fixed_versions": ["2.0"],
                }
            ],
        )
        [tool] = tools_module.make_dependency_tools(Config())
        out = tool.invoke({"package": "Django", "ecosystem": "pypi", "version": "v1.0"})
        assert out.startswith("GHSA-1 [high] bad | fixed in: 2.0")

    def test_requires_version(self):
        assert tools_module.lookup_package("x", "npm", " ", Config()).startswith("ERROR")


class TestGitHistoryTool:
    def test_formats_commits_and_caches_repo(self, monkeypatch):
        commit = MagicMock(sha="abcdef1234")
        commit.commit.author.name = "Ada"
        commit.commit.author.date.date.return_value.isoformat.return_value = "2026-01-02"
        commit.commit.message = "Fix auth\n\nlong body"
        repo = MagicMock()
        repo.get_commits.return_value = [commit]
        client = MagicMock(get_repo=MagicMock(return_value=repo))
        monkeypatch.setattr(tools_module, "make_github_client", lambda _t: client)
        [tool] = tools_module.make_git_history_tools("octo/demo", Config())
        assert tool.invoke({"path": "./src/auth.py"}) == "abcdef1 2026-01-02 Ada: Fix auth"
        tool.invoke({"path": "src/x.py"})
        client.get_repo.assert_called_once()
        repo.get_commits.assert_any_call(path="src/auth.py")
        assert tool.invoke({"path": "../x"}).startswith("ERROR")


class TestRegistry:
    def test_families_and_availability(self, repo):
        names = lambda tools: sorted(t.name for t in tools)  # noqa: E731
        assert names(build_tools(("files",), clone_root=str(repo), config=Config())) == [
            "find_files",
            "list_directory",
            "read_file",
            "search_code",
        ]
        assert (
            names(build_tools(("git_history",), clone_root=str(repo), config=Config())) == []
        )  # no repo name
        assert names(
            build_tools(("scanners", "dependencies"), clone_root=None, config=Config())
        ) == ["query_osv"]
        with pytest.raises(ValueError):
            build_tools(("shell",), clone_root=None, config=Config())
