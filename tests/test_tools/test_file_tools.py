"""Tests for investigator file tools -- especially the path-traversal guard,
which is the one place v3 introduces new attack surface (an LLM now picks the
path argument)."""

import pytest

from src.tools.file_tools import PathEscapesSandboxError, make_file_tools, resolve_safe_path


class TestResolveSafePath:
    def test_normal_path_resolves_inside_root(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")

        resolved = resolve_safe_path(tmp_path, "src/main.py")

        assert resolved == (tmp_path / "src" / "main.py").resolve()

    def test_root_itself_is_allowed(self, tmp_path):
        assert resolve_safe_path(tmp_path, ".") == tmp_path.resolve()

    def test_parent_traversal_is_rejected(self, tmp_path):
        with pytest.raises(PathEscapesSandboxError):
            resolve_safe_path(tmp_path, "../../../etc/passwd")

    def test_absolute_path_escape_is_rejected(self, tmp_path):
        with pytest.raises(PathEscapesSandboxError):
            resolve_safe_path(tmp_path, "/etc/passwd")

    def test_sneaky_dotdot_inside_subdir_is_rejected(self, tmp_path):
        (tmp_path / "src").mkdir()
        with pytest.raises(PathEscapesSandboxError):
            resolve_safe_path(tmp_path, "src/../../outside")


class TestReadFileTool:
    def test_reads_file_contents(self, tmp_path):
        (tmp_path / "app.py").write_text("line1\nline2\nline3\n")
        read_file, _, _ = make_file_tools(str(tmp_path))

        result = read_file.invoke({"path": "app.py"})

        assert result == "line1\nline2\nline3\n"

    def test_line_range_restriction(self, tmp_path):
        (tmp_path / "app.py").write_text("line1\nline2\nline3\nline4\n")
        read_file, _, _ = make_file_tools(str(tmp_path))

        result = read_file.invoke({"path": "app.py", "start_line": 2, "end_line": 3})

        assert result == "line2\nline3"

    def test_path_traversal_returns_error_string_not_exception(self, tmp_path):
        read_file, _, _ = make_file_tools(str(tmp_path))

        result = read_file.invoke({"path": "../../../etc/passwd"})

        assert result.startswith("ERROR")

    def test_nonexistent_file_returns_error(self, tmp_path):
        read_file, _, _ = make_file_tools(str(tmp_path))

        result = read_file.invoke({"path": "does_not_exist.py"})

        assert result.startswith("ERROR")

    def test_large_file_is_truncated(self, tmp_path):
        (tmp_path / "big.txt").write_text("x" * 100_000)
        read_file, _, _ = make_file_tools(str(tmp_path))

        result = read_file.invoke({"path": "big.txt"})

        assert "truncated" in result
        assert len(result) < 100_000


class TestListDirectoryTool:
    def test_lists_files_and_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "README.md").write_text("hi")
        _, list_directory, _ = make_file_tools(str(tmp_path))

        result = list_directory.invoke({"path": "."})

        assert "dir\tsrc" in result
        assert "file\tREADME.md" in result

    def test_path_traversal_returns_error(self, tmp_path):
        _, list_directory, _ = make_file_tools(str(tmp_path))

        result = list_directory.invoke({"path": "../../.."})

        assert result.startswith("ERROR")

    def test_nonexistent_directory_returns_error(self, tmp_path):
        _, list_directory, _ = make_file_tools(str(tmp_path))

        result = list_directory.invoke({"path": "nope"})

        assert result.startswith("ERROR")


class TestSearchCodeTool:
    def test_finds_matching_lines(self, tmp_path):
        (tmp_path / "app.py").write_text("import os\npassword = 'hunter2'\n")
        _, _, search_code = make_file_tools(str(tmp_path))

        result = search_code.invoke({"pattern": r"password\s*="})

        assert "app.py:2" in result

    def test_glob_restricts_search(self, tmp_path):
        (tmp_path / "app.py").write_text("TODO: fix this\n")
        (tmp_path / "notes.txt").write_text("TODO: fix this\n")
        _, _, search_code = make_file_tools(str(tmp_path))

        result = search_code.invoke({"pattern": "TODO", "glob": "*.py"})

        assert "app.py" in result
        assert "notes.txt" not in result

    def test_no_matches_returns_clear_message(self, tmp_path):
        (tmp_path / "app.py").write_text("clean code\n")
        _, _, search_code = make_file_tools(str(tmp_path))

        result = search_code.invoke({"pattern": "nonexistent_pattern_xyz"})

        assert result == "No matches found"

    def test_invalid_regex_returns_error_not_exception(self, tmp_path):
        _, _, search_code = make_file_tools(str(tmp_path))

        result = search_code.invoke({"pattern": "[unclosed"})

        assert result.startswith("ERROR")

    def test_skips_git_directory(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("password = secret\n")
        _, _, search_code = make_file_tools(str(tmp_path))

        result = search_code.invoke({"pattern": "password"})

        assert result == "No matches found"
