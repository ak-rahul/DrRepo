"""Filesystem access to the clone, and the repository-layout collector.

Every walk over a clone goes through `iter_repo_files`, so the skip rules
(vendored/build directories, symlinks, oversized files) live in one place. Skip
checks use path parts *relative to the clone root* -- checking the absolute path
would skip everything if the temp directory sat under a folder named `build`.

`collect_repo_layout` reads the whole tree (the GitHub API only shows the root),
so it finds nested test suites (`src/pkg/tests/`, `*_test.go`, `*.spec.ts`), CI
workflows, lockfiles, policies, and per-language line counts used to normalize
code-quality findings.

`collect_repo_layout` data schema (status OK):
    file_structure: {has_tests, has_ci, has_docs, has_license, has_contributing,
                     has_changelog, has_security_policy, has_code_of_conduct,
                     has_lockfile, has_type_config}
    test_file_count, source_file_count, total_files,
    lines_by_language: {"Python": 1234, ...}, python_lines,
    readme_path: str | None, readme_content: str (capped)
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from drrepo.models import CollectorResult, CollectorStatus

# ------------------------------------------------------------ helpers ---

SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "target",
        "vendor",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        "coverage",
    }
)
DEFAULT_MAX_FILE_BYTES = 512_000


def relative_posix(path: str | Path, root: str | Path) -> str:
    """`path` relative to `root`, with forward slashes; unchanged if not under root.

    Scanners emit absolute paths (ruff) or `./`-prefixed ones (bandit). Reports,
    SARIF, and the LLM must all see stable repo-relative paths instead of a
    temp directory that no longer exists after the run.
    """
    p = Path(path)
    root_path = Path(root).resolve()
    if not p.is_absolute():
        p = root_path / p
    try:
        return p.resolve().relative_to(root_path).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def iter_repo_files(
    root: str | Path, max_bytes: int | None = DEFAULT_MAX_FILE_BYTES
) -> Iterator[Path]:
    """Yield regular files under `root`, pruning skipped dirs and never following symlinks."""
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if max_bytes is not None and path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            yield path


def read_text_file(path: Path) -> str | None:
    """Read a file as UTF-8 text, or return None if it looks binary/unreadable."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="ignore")


# ------------------------------------------------------ layout collector ---

NAME = "repo_layout"

_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
}
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "testing"}
_TEST_FILE_RE = re.compile(
    r"(^test_.+\.py$|.+_test\.py$|.+_test\.go$|.+\.(test|spec)\.[cm]?[jt]sx?$|.+Tests?\.(java|kt|cs)$|.+_spec\.rb$)"
)
_CI_PATHS = (
    ".github/workflows/",
    ".gitlab-ci.yml",
    ".travis.yml",
    ".circleci/",
    "azure-pipelines.yml",
    "Jenkinsfile",
    "bitbucket-pipelines.yml",
    ".drone.yml",
    "buildkite",
)
_LOCKFILES = {
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "pdm.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
}
_TYPE_CONFIGS = {"mypy.ini", "tsconfig.json", "pyrightconfig.json", ".mypy.ini"}
_README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
_MAX_README_CHARS = 100_000


def _count_lines(path: Path) -> int:
    text = read_text_file(path)
    if text is None:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def collect_repo_layout(clone_path: str) -> CollectorResult:
    root = Path(clone_path)
    if not root.is_dir():
        return CollectorResult(
            name=NAME, status=CollectorStatus.SKIPPED, detail="No local clone available"
        )

    fs = {
        "has_tests": False,
        "has_ci": False,
        "has_docs": False,
        "has_license": False,
        "has_contributing": False,
        "has_changelog": False,
        "has_security_policy": False,
        "has_code_of_conduct": False,
        "has_lockfile": False,
        "has_type_config": False,
    }
    lines_by_language: dict[str, int] = {}
    test_files = source_files = total_files = 0
    readme_path: str | None = None

    for path in iter_repo_files(root, max_bytes=2_000_000):
        total_files += 1
        rel = relative_posix(path, root)
        parts = rel.split("/")
        name = parts[-1]
        lower = name.lower()
        dirs_lower = {p.lower() for p in parts[:-1]}

        is_test = bool(dirs_lower & _TEST_DIRS) or bool(_TEST_FILE_RE.match(name))
        if is_test:
            fs["has_tests"] = True
            test_files += 1
        if any(rel.startswith(ci) or rel == ci.rstrip("/") for ci in _CI_PATHS):
            fs["has_ci"] = True
        if parts[0].lower() in ("docs", "doc", "documentation") and len(parts) > 1:
            fs["has_docs"] = True
        if len(parts) == 1 or parts[0] == ".github":
            if lower.startswith(("license", "licence", "copying")):
                fs["has_license"] = True
            if lower.startswith("contributing"):
                fs["has_contributing"] = True
            if lower.startswith(("changelog", "changes", "history", "news")):
                fs["has_changelog"] = True
            if lower.startswith("security"):
                fs["has_security_policy"] = True
            if lower.startswith("code_of_conduct"):
                fs["has_code_of_conduct"] = True
        if len(parts) == 1 and lower in _README_NAMES and readme_path is None:
            readme_path = rel
        if name in _LOCKFILES:
            fs["has_lockfile"] = True
        if name in _TYPE_CONFIGS:
            fs["has_type_config"] = True

        language = _LANGUAGES.get(path.suffix.lower())
        if language and not is_test:
            source_files += 1
            lines_by_language[language] = lines_by_language.get(language, 0) + _count_lines(path)

    # pyproject.toml with a [tool.mypy]/[tool.pyright] table also counts.
    pyproject = root / "pyproject.toml"
    if not fs["has_type_config"] and pyproject.is_file():
        text = read_text_file(pyproject) or ""
        fs["has_type_config"] = "[tool.mypy]" in text or "[tool.pyright]" in text

    readme_content = ""
    if readme_path:
        readme_content = (read_text_file(root / readme_path) or "")[:_MAX_README_CHARS]

    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={
            "file_structure": fs,
            "test_file_count": test_files,
            "source_file_count": source_files,
            "total_files": total_files,
            "lines_by_language": dict(sorted(lines_by_language.items(), key=lambda kv: -kv[1])),
            "python_lines": lines_by_language.get("Python", 0),
            "readme_path": readme_path,
            "readme_content": readme_content,
        },
    )
