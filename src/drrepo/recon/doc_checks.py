"""Documentation checks that need no judgment: links, docstrings, documented commands.

Three deterministic checks over the clone:

- **Internal links** in the README and `docs/**/*.md`: relative file targets
  must exist inside the repository, and `#anchors` must match a heading (GitHub's
  slug rules) or an explicit `id`/`name` in the target file. External URLs are
  never fetched.
- **Docstring coverage** of public Python APIs (module-level functions and
  classes, and public methods of public classes) in package code, via `ast`.
  Tests, examples, docs, scripts and private names are left out.
- **Documented commands** in shell code blocks: `npm run X` / `yarn X` /
  `pnpm run X` / `bun run X` need a `package.json` script, `make X` needs a
  Makefile target, and a command named after the project needs a declared entry
  point (`[project.scripts]`, Poetry scripts, or `package.json` `bin`).

`data` schema (status OK):
    markdown_files: [path], links_checked: int,
    broken_links: [{file, line, target, reason}],
    docstrings: {public: int, documented: int, coverage: float | None,
                 undocumented: [{file, line, name}]}   (up to 30 samples),
    commands_checked: int,
    missing_commands: [{file, line, command, reason}]
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix

NAME = "doc_checks"
MAX_MARKDOWN_FILES = 200
MAX_LINKS = 3000
MAX_PYTHON_FILES = 2000
MAX_SAMPLES = 30

_INLINE_LINK = re.compile(
    r"!?\[[^\]\n]{0,300}\]\(\s*<?([^)\s>]{1,500})>?(?:\s+\"[^\"\n]{0,300}\")?\s*\)"
)
_REFERENCE_DEF = re.compile(
    r"^\s{0,3}\[[^\]\n]{1,300}\]:\s*<?(\S{1,500}?)>?(?:\s+\"[^\"\n]*\")?\s*$"
)
# The info string is the first word after the fence; MyST directives ("{note}") are not shell.
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*(\S*)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
# MyST target labels: "(label)=" on a line of its own.
_MYST_LABEL = re.compile(r"^\s{0,3}\(([^()\s]{1,200})\)=\s*$")
# In Sphinx (MyST) docs a link target without one of these suffixes is a
# cross-reference to a label, object or document name, not a file path.
_FILE_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".rst",
        ".txt",
        ".ipynb",
        ".html",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".pdf",
        ".py",
        ".toml",
        ".json",
        ".yml",
        ".yaml",
        ".cfg",
        ".ini",
        ".sh",
    }
)
_HTML_ANCHOR = re.compile(r"""<[^>]{0,200}?\b(?:id|name)\s*=\s*["']([^"']{1,200})["']""")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_SHELL_LANGS = {"", "bash", "sh", "shell", "console", "zsh", "terminal", "shell-session"}
_NON_PACKAGE_DIRS = {
    "tests",
    "test",
    "testing",
    "docs",
    "doc",
    "examples",
    "example",
    "scripts",
    "benchmarks",
    "migrations",
}
# `yarn <word>` runs a script unless <word> is one of yarn's own commands.
_YARN_BUILTINS = {
    "add",
    "audit",
    "bin",
    "cache",
    "config",
    "create",
    "dlx",
    "exec",
    "global",
    "help",
    "info",
    "init",
    "install",
    "link",
    "list",
    "login",
    "logout",
    "node",
    "outdated",
    "pack",
    "plugin",
    "publish",
    "remove",
    "set",
    "unlink",
    "up",
    "upgrade",
    "version",
    "why",
    "workspace",
    "workspaces",
}


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading (before duplicate numbering)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # [text](url) -> text
    text = re.sub(r"<[^>]{0,200}>", "", text).replace("`", "").replace("*", "")
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def anchors(text: str) -> set[str]:
    """Every anchor a Markdown file defines: heading slugs (with GitHub's -1, -2
    suffixes for repeats), explicit HTML `id`/`name` attributes, and MyST
    `(label)=` targets."""
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        label = _MYST_LABEL.match(line)
        if label:
            found.add(label.group(1).lower())
            continue
        match = _HEADING.match(line)
        if match:
            slug = github_slug(match.group(2))
            n = counts.get(slug, 0)
            counts[slug] = n + 1
            found.add(slug if n == 0 else f"{slug}-{n}")
        found.update(a.lower() for a in _HTML_ANCHOR.findall(line))
    return found


def _links(text: str) -> list[tuple[int, str]]:
    out = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or len(line) > 5000:
            continue
        stripped = re.sub(r"`[^`]*`", "", line)  # links inside inline code aren't links
        out += [(number, m.group(1)) for m in _INLINE_LINK.finditer(stripped)]
        ref = _REFERENCE_DEF.match(stripped)
        if ref:
            out.append((number, ref.group(1)))
    return out


def _markdown_files(root: Path) -> list[Path]:
    readmes = sorted(
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name.lower().startswith("readme")
        and p.suffix.lower() in (".md", ".markdown")
    )
    docs = root / "docs"
    in_docs = (
        [p for p in iter_repo_files(docs) if p.suffix.lower() in (".md", ".markdown")]
        if docs.is_dir()
        else []
    )
    return (readmes + in_docs)[:MAX_MARKDOWN_FILES]


def _in_sphinx_docs(path: Path, root: Path) -> bool:
    """True if a Sphinx `conf.py` sits in the file's directory or one above it (within root)."""
    for directory in path.parents:
        if (directory / "conf.py").is_file():
            return True
        if directory == root:
            return False
    return False


def check_links(root: Path, files: list[Path]) -> tuple[int, list[dict[str, Any]]]:
    cache: dict[Path, set[str]] = {}

    def anchors_of(path: Path) -> set[str]:
        if path not in cache:
            cache[path] = anchors(read_text_file(path) or "")
        return cache[path]

    checked = 0
    broken: list[dict[str, Any]] = []
    for md in files:
        text = read_text_file(md) or ""
        rel_md = relative_posix(md, root)
        sphinx = _in_sphinx_docs(md, root)
        for line, raw in _links(text):
            if checked >= MAX_LINKS:
                return checked, broken
            if _SCHEME.match(raw) or raw.startswith("//"):
                continue  # external: never fetched
            target, _, anchor = unquote(raw).partition("#")
            target = target.split("?", 1)[0]
            if sphinx and target and Path(target).suffix.lower() not in _FILE_SUFFIXES:
                continue  # a MyST cross-reference ([](attrs.frozen), [](api-validators))
            checked += 1
            if target:
                base = root if target.startswith("/") else md.parent
                resolved = (base / target.lstrip("/")).resolve()
                if resolved != root and root not in resolved.parents:
                    broken.append(
                        {
                            "file": rel_md,
                            "line": line,
                            "target": raw,
                            "reason": "points outside the repository",
                        }
                    )
                    continue
                if not resolved.exists():
                    broken.append(
                        {"file": rel_md, "line": line, "target": raw, "reason": "file not found"}
                    )
                    continue
            else:
                resolved = md
            if (
                anchor
                and resolved.is_file()
                and resolved.suffix.lower() in (".md", ".markdown")
                and anchor.lower() not in anchors_of(resolved)
            ):
                broken.append(
                    {"file": rel_md, "line": line, "target": raw, "reason": "anchor not found"}
                )
    return checked, broken


def _is_package_code(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    if (
        name in ("setup.py", "conftest.py", "noxfile.py", "manage.py")
        or name.startswith("test_")
        or name.endswith("_test.py")
    ):
        return False
    return not any(p.lower() in _NON_PACKAGE_DIRS or p.startswith(".") for p in parts[:-1])


def docstring_coverage(root: Path) -> dict[str, Any]:
    public = documented = 0
    undocumented: list[dict[str, Any]] = []
    files = 0
    for path in iter_repo_files(root):
        if path.suffix != ".py":
            continue
        rel = relative_posix(path, root)
        if not _is_package_code(rel):
            continue
        files += 1
        if files > MAX_PYTHON_FILES:
            break
        try:
            tree = ast.parse(read_text_file(path) or "")
        except (SyntaxError, ValueError, RecursionError):
            continue
        candidates: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
        for node in tree.body:
            if isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            ) and not node.name.startswith("_"):
                candidates.append(node)
                if isinstance(node, ast.ClassDef):
                    candidates += [
                        m
                        for m in node.body
                        if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                        and not m.name.startswith("_")
                    ]
        for node in candidates:
            public += 1
            if ast.get_docstring(node):
                documented += 1
            elif len(undocumented) < MAX_SAMPLES:
                undocumented.append({"file": rel, "line": node.lineno, "name": node.name})
    return {
        "public": public,
        "documented": documented,
        "coverage": round(documented / public, 3) if public else None,
        "undocumented": undocumented,
    }


def _project_facts(root: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "npm_scripts": None,
        "make_targets": None,
        "names": set(),
        "entry_points": set(),
    }
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(read_text_file(pyproject) or "")
        except tomllib.TOMLDecodeError:
            data = {}
        project = data.get("project") or {}
        poetry = (data.get("tool") or {}).get("poetry") or {}
        for name in (project.get("name"), poetry.get("name")):
            if isinstance(name, str):
                facts["names"].add(name.lower())
        for scripts in (project.get("scripts"), poetry.get("scripts")):
            if isinstance(scripts, dict):
                facts["entry_points"] |= {str(k).lower() for k in scripts}
    package = root / "package.json"
    if package.is_file():
        try:
            pkg = json.loads(read_text_file(package) or "{}")
        except json.JSONDecodeError:
            pkg = {}
        if isinstance(pkg, dict):
            scripts = pkg.get("scripts")
            facts["npm_scripts"] = set(scripts) if isinstance(scripts, dict) else set()
            name = pkg.get("name")
            if isinstance(name, str):
                facts["names"].add(name.lower().rsplit("/", 1)[-1])
            bins = pkg.get("bin")
            if isinstance(bins, dict):
                facts["entry_points"] |= {str(k).lower() for k in bins}
            elif isinstance(bins, str) and isinstance(name, str):
                facts["entry_points"].add(name.lower().rsplit("/", 1)[-1])
    makefile = next(
        (root / n for n in ("Makefile", "makefile", "GNUmakefile") if (root / n).is_file()), None
    )
    if makefile is not None:
        text = read_text_file(makefile) or ""
        facts["make_targets"] = set(
            re.findall(r"^([A-Za-z0-9_.\-/]+)\s*:(?!=)", text, re.MULTILINE)
        )
    return facts


def _shell_lines(text: str) -> list[tuple[int, str]]:
    out, lang = [], None
    for number, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence:
            lang = None if lang is not None else fence.group(2).lower()
            continue
        if lang in _SHELL_LANGS:
            command = line.strip()
            for prompt in ("$ ", "> ", "% "):
                command = command.removeprefix(prompt)
            if command and not command.startswith("#"):
                out.append((number, command))
    return out


# Prefixes that run a project's command from its environment: `uv run drrepo` is `drrepo`.
_RUNNERS = (
    ("uv", "run"),
    ("poetry", "run"),
    ("pdm", "run"),
    ("hatch", "run"),
    ("rye", "run"),
    ("pipx", "run"),
    ("uvx",),
    ("npx",),
)
# Runner options followed by a separate value (`uv run --with httpx drrepo`).
_VALUE_OPTIONS = {"--with", "--from", "--python", "-p", "--package", "--env-file"}


def _strip_runner(words: list[str]) -> list[str]:
    """The command a runner prefix launches, with the runner's own options removed."""
    for runner in _RUNNERS:
        if tuple(words[: len(runner)]) == runner:
            rest = words[len(runner) :]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in _VALUE_OPTIONS else rest[1:]
            return rest
    return words


def check_commands(root: Path, files: list[Path]) -> tuple[int, list[dict[str, Any]]]:
    facts = _project_facts(root)
    checked, missing = 0, []
    for md in files:
        rel = relative_posix(md, root)
        for line, command in _shell_lines(read_text_file(md) or ""):
            words = _strip_runner(command.split())
            if not words:
                continue
            reason = None
            if (
                facts["npm_scripts"] is not None
                and len(words) >= 2
                and (
                    (words[0] in ("npm", "pnpm", "bun") and words[1] == "run" and len(words) >= 3)
                    or (
                        words[0] == "yarn"
                        and words[1] not in _YARN_BUILTINS
                        and not words[1].startswith("-")
                    )
                )
            ):
                script = words[2] if words[1] == "run" else words[1]
                checked += 1
                if script not in facts["npm_scripts"]:
                    reason = f"package.json has no '{script}' script"
            elif (
                words[0] == "make"
                and facts["make_targets"] is not None
                and len(words) >= 2
                and not words[1].startswith("-")
                and "=" not in words[1]
            ):
                checked += 1
                if words[1] not in facts["make_targets"]:
                    reason = f"the Makefile has no '{words[1]}' target"
            elif words[0] in facts["names"]:  # commands are case-sensitive; "Click" is prose
                checked += 1
                if words[0] not in facts["entry_points"]:
                    reason = f"'{words[0]}' is not a declared entry point"
            if reason:
                missing.append(
                    {"file": rel, "line": line, "command": command[:200], "reason": reason}
                )
    return checked, missing


def collect_doc_checks(clone_root: str) -> CollectorResult:
    root = Path(clone_root).resolve()
    if not root.is_dir():
        return CollectorResult.skipped(NAME, "no clone available")
    files = _markdown_files(root)
    links_checked, broken = check_links(root, files)
    commands_checked, missing = check_commands(root, files)
    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={
            "markdown_files": [relative_posix(p, root) for p in files],
            "links_checked": links_checked,
            "broken_links": broken,
            "docstrings": docstring_coverage(root),
            "commands_checked": commands_checked,
            "missing_commands": missing,
        },
    )
