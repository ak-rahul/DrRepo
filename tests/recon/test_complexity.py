"""Complexity (lizard) and copy-paste metrics over a clone."""

from drrepo.config import Config
from drrepo.recon.complexity import (
    collect_complexity,
    find_duplicates,
    is_product_source,
    normalized_lines,
)

BRANCHY = (
    "def tangled(x):\n"
    + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
    + "    return -1\n"
)

BLOCK = "".join(f"    total = total + value_{i} * {i}\n" for i in range(10))


def test_product_source_excludes_tests_vendored_and_minified():
    assert is_product_source("src/app/core.py")
    assert is_product_source("lib/index.ts")
    for path in (
        "tests/test_core.py",
        "src/app/test_core.py",
        "pkg/server_test.go",
        "web/app.spec.tsx",
        "static/jquery.min.js",
        "third_party/lib.c",
        "docs/conf.py",
        ".github/scripts/x.py",
        "README.md",
    ):
        assert not is_product_source(path), path


def test_normalized_lines_drop_blank_comment_and_brace_lines():
    text = "def f():\n\n    # note\n    x  =  1\n    }\n    // c\n    return x\n"
    assert normalized_lines(text) == [(1, "def f():"), (4, "x = 1"), (7, "return x")]


def test_find_duplicates_merges_windows_into_blocks():
    shared = [(n, f"line {n}") for n in range(1, 13)]
    files = {
        "a.py": [(100, "only in a"), *shared],
        "b.py": [(n + 50, text) for n, text in shared],
        "c.py": [(1, "unique"), (2, "also unique")],
    }
    result = find_duplicates(files, window=8)
    assert result["lines"] == 27 and result["duplicated_lines"] == 24
    assert result["ratio"] == round(24 / 27, 4)
    assert {(b["file"], b["line"], b["end_line"], b["lines"]) for b in result["blocks"]} == {
        ("a.py", 1, 12, 12),
        ("b.py", 51, 62, 12),
    }
    a_block = next(b for b in result["blocks"] if b["file"] == "a.py")
    assert a_block["also_in"] == {"file": "b.py", "line": 51}
    assert find_duplicates({})["ratio"] is None


def test_collect_measures_product_code_only(make_repo):
    root = make_repo(
        {
            "src/pkg/core.py": BRANCHY + "\ndef simple():\n    return 1\n",
            "src/pkg/one.py": "def one(total):\n" + BLOCK + "    return total\n",
            "src/pkg/two.py": "def two(total):\n" + BLOCK + "    return total\n",
            "tests/test_core.py": BRANCHY.replace("tangled", "test_tangled"),
            "web/app.min.js": "var a=1;" * 200,
        }
    )
    data = collect_complexity(str(root), Config()).data
    assert data["files_analyzed"] == 3 and data["languages"] == {"py": 3}
    assert [f["name"] for f in data["complex_functions"]] == ["tangled"]
    assert data["complex_functions"][0]["file"] == "src/pkg/core.py"
    assert data["complex_count"] == 1 and data["long_count"] == 0
    duplication = data["duplication"]
    assert duplication["duplicated_lines"] == 22  # the shared body and return, in both files
    assert {b["file"] for b in duplication["blocks"]} == {"src/pkg/one.py", "src/pkg/two.py"}
    assert data["truncated"] is False


def test_collect_skips_when_disabled_or_empty(make_repo):
    root = make_repo({"README.md": "# x\n"})
    assert collect_complexity(str(root), Config(enable_complexity_metrics=False)).status.value == (
        "skipped"
    )
    empty = collect_complexity(str(root), Config())
    assert empty.status.value == "ok" and empty.detail == "No product source code found"
    assert collect_complexity(str(root / "missing"), Config()).status.value == "skipped"
