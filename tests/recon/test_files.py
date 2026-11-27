from pathlib import Path

from drrepo.recon.files import collect_repo_layout, iter_repo_files, read_text_file, relative_posix


def test_iter_skips_vendored_dirs_relative_to_root(tmp_path, make_repo):
    # The clone itself lives under a dir named "build": nothing must be skipped for that.
    root = tmp_path / "build" / "clone"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1")
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "node_modules" / "dep" / "index.js").write_text("x")
    files = [relative_posix(p, root) for p in iter_repo_files(root)]
    assert files == ["src/a.py"]


def test_iter_skips_large_files(make_repo):
    root = make_repo({"small.txt": "a", "big.txt": "b" * 2000})
    assert [p.name for p in iter_repo_files(root, max_bytes=1000)] == ["small.txt"]


def test_read_text_file_detects_binary(make_repo):
    root = make_repo({"bin.dat": b"\x00\x01\x02", "t.txt": "hello"})
    assert read_text_file(root / "bin.dat") is None
    assert read_text_file(root / "t.txt") == "hello"


def test_relative_posix_handles_absolute_and_dot_prefixed(tmp_path):
    root = tmp_path
    assert relative_posix(root / "a" / "b.py", root) == "a/b.py"
    assert relative_posix("./a/b.py", root) == "a/b.py"
    assert relative_posix(Path("/elsewhere/x.py"), root).endswith("x.py")


def test_layout_detects_nested_tests_ci_and_lines(make_repo):
    root = make_repo(
        {
            "src/pkg/core.py": "a = 1\n\nb = 2\n",
            "src/pkg/tests/test_core.py": "def test(): pass\n",
            "web/app.spec.ts": "it('x')",
            ".github/workflows/ci.yml": "on: push",
            "docs/index.md": "# Docs",
            "LICENSE": "MIT",
            "SECURITY.md": "report privately",
            "uv.lock": "",
            "README.md": "# Title\n",
        }
    )
    result = collect_repo_layout(str(root))
    data = result.data
    fs = data["file_structure"]
    assert fs["has_tests"] and fs["has_ci"] and fs["has_docs"] and fs["has_license"]
    assert fs["has_security_policy"] and fs["has_lockfile"]
    assert not fs["has_contributing"]
    assert data["python_lines"] == 2  # blank lines and test files excluded
    assert data["test_file_count"] == 2
    assert data["readme_path"] == "README.md"
    assert data["readme_content"].startswith("# Title")


def test_layout_type_config_from_pyproject(make_repo):
    root = make_repo({"pyproject.toml": "[tool.mypy]\nstrict = true\n"})
    assert collect_repo_layout(str(root)).data["file_structure"]["has_type_config"]


def test_layout_missing_clone(tmp_path):
    assert collect_repo_layout(str(tmp_path / "nope")).status.value == "skipped"
