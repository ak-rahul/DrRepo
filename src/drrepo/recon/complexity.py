"""Complexity and duplication metrics over the clone's source code.

Two deterministic measurements, both parse-only:

- **Complexity** with `lizard` (multi-language): cyclomatic complexity (CCN)
  and length (NLOC) per function. Functions over the thresholds are sampled,
  worst first.
- **Duplication** with a line-window detector: each file's code lines are
  normalized (whitespace collapsed; blank, comment-only and brace-only lines
  dropped), and every window of `DUPLICATE_WINDOW` consecutive lines is hashed.
  A window seen at two or more places marks its lines duplicated. It finds
  copy-paste, not renamed or reordered clones.

Test, example, documentation and vendored code is left out, as are minified
files: complexity there says little about the product. File count, file size
and wall time are capped; a capped run says so in `truncated`.

`data` schema (status OK):
    files_analyzed: int, functions: int, nloc: int, languages: {ext: files},
    average_ccn: float | None, truncated: bool,
    thresholds: {ccn, nloc, window},
    complex_count: int, complex_functions: [{file, line, name, ccn, nloc}]
        (CCN above the threshold, worst first, up to 30),
    long_count: int, long_functions: [{file, line, name, ccn, nloc}]
        (NLOC above the threshold, longest first, up to 30),
    duplication: {lines: int, duplicated_lines: int, ratio: float | None,
                  blocks: [{file, line, end_line, lines, also_in: {file, line}}]}  (up to 20)
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.log import logger
from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix

NAME = "complexity"

CCN_THRESHOLD = 15
NLOC_THRESHOLD = 100
DUPLICATE_WINDOW = 8
MAX_FILES = 2000
MAX_FILE_BYTES = 300_000
MAX_SAMPLES = 30
MAX_BLOCKS = 20
# Lines this long are generated or minified, not written by hand.
_MAX_LINE_CHARS = 500

SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".java",
        ".kt",
        ".scala",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
        ".cs",
        ".swift",
    }
)
_EXCLUDED_DIRS = frozenset(
    {
        "tests",
        "test",
        "testing",
        "__tests__",
        "spec",
        "specs",
        "examples",
        "example",
        "docs",
        "doc",
        "benchmarks",
        "fixtures",
        "migrations",
        "third_party",
        "thirdparty",
        "external",
        "generated",
    }
)
_TEST_FILE = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|\.min\.js$)")
_COMMENT_ONLY = re.compile(r"^(#|//|/\*|\*|\*/|--)")
_PUNCTUATION_ONLY = re.compile(r"^[\s{}()\[\];,]*$")
_SPACES = re.compile(r"\s+")


def is_product_source(rel: str) -> bool:
    """Hand-written product code: a source suffix, outside tests, examples, docs and vendored dirs."""
    parts = rel.split("/")
    name = parts[-1]
    if Path(name).suffix.lower() not in SOURCE_SUFFIXES or _TEST_FILE.search(name):
        return False
    return not any(p.lower() in _EXCLUDED_DIRS or p.startswith(".") for p in parts[:-1])


def normalized_lines(text: str) -> list[tuple[int, str]]:
    """`(line number, normalized text)` for each line that carries code."""
    kept = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = _SPACES.sub(" ", raw.strip())
        if not line or _COMMENT_ONLY.match(line) or _PUNCTUATION_ONLY.match(line):
            continue
        kept.append((number, line))
    return kept


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    """`(first, last)` of each run of consecutive integers in sorted `indices`."""
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def find_duplicates(
    files: dict[str, list[tuple[int, str]]], window: int = DUPLICATE_WINDOW
) -> dict[str, Any]:
    """Duplicated code lines across `files` ({path: normalized lines})."""
    seen: dict[bytes, list[tuple[str, int]]] = defaultdict(list)
    for path, lines in files.items():
        for start in range(len(lines) - window + 1):
            chunk = "\n".join(text for _, text in lines[start : start + window])
            seen[hashlib.blake2b(chunk.encode(), digest_size=12).digest()].append((path, start))

    covered: dict[str, set[int]] = defaultdict(set)
    partner: dict[tuple[str, int], tuple[str, int]] = {}
    for places in seen.values():
        if len(places) < 2:
            continue
        for index, (path, start) in enumerate(places):
            covered[path].update(range(start, start + window))
            other = places[1] if index == 0 else places[0]
            partner.setdefault((path, start), other)

    blocks: list[dict[str, Any]] = []
    for path in sorted(covered):
        lines = files[path]
        # A run starts at a window start, so it always has a partner location.
        for first, last in _runs(sorted(covered[path])):
            other_path, other_start = partner.get((path, first), (path, first))
            blocks.append(
                {
                    "file": path,
                    "line": lines[first][0],
                    "end_line": lines[last][0],
                    "lines": last - first + 1,
                    "also_in": {"file": other_path, "line": files[other_path][other_start][0]},
                }
            )

    total = sum(len(lines) for lines in files.values())
    duplicated = sum(len(indices) for indices in covered.values())
    blocks.sort(key=lambda b: (-b["lines"], b["file"], b["line"]))
    return {
        "lines": total,
        "duplicated_lines": duplicated,
        "ratio": round(duplicated / total, 4) if total else None,
        "blocks": blocks[:MAX_BLOCKS],
    }


def _function_entry(rel: str, function: Any) -> dict[str, Any]:
    return {
        "file": rel,
        "line": int(function.start_line),
        "name": str(function.name)[:120],
        "ccn": int(function.cyclomatic_complexity),
        "nloc": int(function.nloc),
    }


def collect_complexity(clone_path: str, config: Config) -> CollectorResult:
    if not config.enable_complexity_metrics:
        return CollectorResult.skipped(NAME, "Disabled by config")
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult.skipped(NAME, "No local clone available")
    try:
        import lizard
    except ImportError:  # pragma: no cover - a declared dependency
        return CollectorResult.skipped(NAME, "lizard is not installed")

    analyzer = lizard.FileAnalyzer(lizard.get_extensions([]))
    deadline = time.monotonic() + config.collector_timeout_seconds
    truncated = False
    languages: dict[str, int] = defaultdict(int)
    functions: list[dict[str, Any]] = []
    normalized: dict[str, list[tuple[int, str]]] = {}
    nloc = 0

    for path in iter_repo_files(root, max_bytes=MAX_FILE_BYTES):
        rel = relative_posix(path, root)
        if not is_product_source(rel):
            continue
        if len(normalized) >= MAX_FILES or time.monotonic() > deadline:
            truncated = True
            break
        text = read_text_file(path)
        if not text or max((len(line) for line in text.splitlines()), default=0) > _MAX_LINE_CHARS:
            continue
        try:
            info = analyzer.analyze_source_code(rel, text)
        except Exception as e:  # a parser bug on one file never fails the collector
            logger.debug(f"lizard could not parse {rel}: {e}")
            continue
        languages[Path(rel).suffix.lower().lstrip(".")] += 1
        nloc += int(info.nloc)
        functions.extend(_function_entry(rel, f) for f in info.function_list)
        normalized[rel] = normalized_lines(text)

    complex_functions = sorted(
        (f for f in functions if f["ccn"] > CCN_THRESHOLD),
        key=lambda f: (-f["ccn"], f["file"], f["line"]),
    )
    long_functions = sorted(
        (f for f in functions if f["nloc"] > NLOC_THRESHOLD),
        key=lambda f: (-f["nloc"], f["file"], f["line"]),
    )
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={
            "files_analyzed": len(normalized),
            "functions": len(functions),
            "nloc": nloc,
            "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
            "average_ccn": (
                round(sum(f["ccn"] for f in functions) / len(functions), 2) if functions else None
            ),
            "truncated": truncated,
            "thresholds": _thresholds(),
            "complex_count": len(complex_functions),
            "complex_functions": complex_functions[:MAX_SAMPLES],
            "long_count": len(long_functions),
            "long_functions": long_functions[:MAX_SAMPLES],
            "duplication": find_duplicates(normalized),
        },
        detail=None if normalized else "No product source code found",
    )


def _thresholds() -> dict[str, int]:
    return {"ccn": CCN_THRESHOLD, "nloc": NLOC_THRESHOLD, "window": DUPLICATE_WINDOW}
