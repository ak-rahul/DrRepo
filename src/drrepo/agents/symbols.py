"""Code-symbol index: where things are defined, and who mentions them.

Investigators otherwise navigate with `search_code`, spending tool calls on
questions like "where is `authenticate` defined, and who calls it?". The index
answers those directly. It is built lazily, on the first symbol tool call of a
run, kept in memory for that run only, and shared by the categories that
investigate in parallel; it is never persisted, so it can't go stale.

Extraction is deterministic and needs no extra dependency:

- **Python**: the standard `ast` module, so definitions, nesting (`Class.method`),
  signatures and line ranges are exact. Files that don't parse fall back to the
  line patterns below.
- **JavaScript/TypeScript, Go, Java/Kotlin/C#, Ruby, Rust, PHP**: conservative
  line patterns for functions, classes, methods and types. They find the
  common forms and give a start line (no end line); they never execute or
  evaluate anything.

References are whole-word matches of a symbol's final name segment in indexed
source files, with definition lines left out. A name is not resolved through
imports or scopes, so a reference list is a lead to read, not a call graph.
"""

from __future__ import annotations

import ast
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix

MAX_INDEXED_FILES = 5000
MAX_SYMBOLS = 100_000
BUILD_TIME_BUDGET_SECONDS = 20.0
MAX_SIGNATURE_CHARS = 160
NAME_RE = re.compile(r"^[A-Za-z_$][\w$]{0,100}(?:\.[A-Za-z_$][\w$]{0,100}){0,4}$")

LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".kt": "java",
    ".cs": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".php": "php",
}

_JS = [
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("
        ),
    ),
    (
        "class",
        re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]{1,80})?=\s*(?:async\s+)?(?:function\b|\([^)]{0,200}\)\s*(?::[^=]{1,80})?=>|[A-Za-z_$][\w$]*\s*=>)"
        ),
    ),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)")),
]
_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "python": [
        ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_]\w*)")),
    ],
    "javascript": _JS,
    "typescript": _JS,
    "go": [
        ("function", re.compile(r"^func\s+(?:\([^)]{0,120}\)\s*)?([A-Za-z_]\w*)\s*[\[(]")),
        ("type", re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b")),
    ],
    "java": [
        (
            "class",
            re.compile(
                r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|data|open|partial)\s+)*(?:class|interface|enum|record|object)\s+([A-Za-z_]\w*)"
            ),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|synchronized|override|async|virtual)\s+)+[\w<>\[\],.? ]{1,80}?\s+([A-Za-z_]\w*)\s*\([^;]*$"
            ),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:(?:private|public|protected|internal|override|suspend)\s+)*fun\s+(?:<[^>]{1,60}>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\("
            ),
        ),
    ],
    "ruby": [
        ("function", re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)")),
        ("class", re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)")),
    ],
    "rust": [
        (
            "function",
            re.compile(
                r"^\s*(?:pub(?:\([^)]{1,30}\))?\s+)?(?:const\s+|async\s+|unsafe\s+|extern\s+\"\w+\"\s+)*fn\s+([A-Za-z_]\w*)"
            ),
        ),
        (
            "type",
            re.compile(
                r"^\s*(?:pub(?:\([^)]{1,30}\))?\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)"
            ),
        ),
    ],
    "php": [
        (
            "function",
            re.compile(
                r"^\s*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+&?\s*([A-Za-z_]\w*)\s*\("
            ),
        ),
        (
            "class",
            re.compile(
                r"^\s*(?:(?:final|abstract|readonly)\s+)*(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)"
            ),
        ),
    ],
}


@dataclass(frozen=True)
class Symbol:
    name: str  # qualified within its file: "Class.method"
    kind: str  # function | method | class | type
    path: str  # repo-relative POSIX
    line: int
    end_line: int | None
    signature: str

    @property
    def short_name(self) -> str:
        return self.name.rsplit(".", 1)[-1]


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SIGNATURE_CHARS else text[: MAX_SIGNATURE_CHARS - 1] + "…"


def python_symbols(path: str, text: str) -> list[Symbol] | None:
    """Exact definitions from `ast`, or None if the file doesn't parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    found: list[Symbol] = []

    def visit(node: ast.AST, prefix: str, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualified = f"{prefix}{child.name}"
                keyword = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                returns = f" -> {ast.unparse(child.returns)}" if child.returns else ""
                signature = f"{keyword} {child.name}({ast.unparse(child.args)}){returns}"
                kind = "method" if in_class else "function"
                found.append(
                    Symbol(qualified, kind, path, child.lineno, child.end_lineno, _clip(signature))
                )
                visit(child, f"{qualified}.", False)
            elif isinstance(child, ast.ClassDef):
                qualified = f"{prefix}{child.name}"
                bases = ", ".join(ast.unparse(b) for b in child.bases)
                signature = f"class {child.name}" + (f"({bases})" if bases else "")
                found.append(
                    Symbol(
                        qualified, "class", path, child.lineno, child.end_lineno, _clip(signature)
                    )
                )
                visit(child, f"{qualified}.", True)
            else:
                visit(child, prefix, in_class)

    visit(tree, "", False)
    return found


def pattern_symbols(path: str, text: str, language: str) -> list[Symbol]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) > 1000:
            continue
        for kind, pattern in _PATTERNS[language]:
            match = pattern.match(line)
            if match:
                found.append(Symbol(match.group(1), kind, path, number, None, _clip(line)))
                break
    return found


@dataclass
class SymbolIndex:
    """Lazily built, thread-safe index of one clone's definitions."""

    root: Path
    symbols: list[Symbol] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # indexed source files
    truncated: str | None = None  # why indexing stopped early, if it did
    _built: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def build(self) -> SymbolIndex:
        with self._lock:
            if self._built:
                return self
            started = time.monotonic()
            root = self.root.resolve()
            for path in iter_repo_files(root):
                language = LANGUAGES.get(path.suffix.lower())
                if language is None:
                    continue
                if len(self.files) >= MAX_INDEXED_FILES:
                    self.truncated = f"stopped at {MAX_INDEXED_FILES} files"
                    break
                if time.monotonic() - started > BUILD_TIME_BUDGET_SECONDS:
                    self.truncated = f"stopped after {BUILD_TIME_BUDGET_SECONDS:.0f}s"
                    break
                text = read_text_file(path)
                if text is None:
                    continue
                rel = relative_posix(path, root)
                self.files.append(rel)
                found = python_symbols(rel, text) if language == "python" else None
                self.symbols += found if found is not None else pattern_symbols(rel, text, language)
                if len(self.symbols) >= MAX_SYMBOLS:
                    self.truncated = f"stopped at {MAX_SYMBOLS} symbols"
                    break
            self._built = True
            return self

    def definitions(self, name: str) -> list[Symbol]:
        """Exact matches on the qualified name, else on the final segment."""
        self.build()
        exact = [s for s in self.symbols if s.name == name]
        if exact:
            return exact
        short = name.rsplit(".", 1)[-1]
        return [s for s in self.symbols if s.short_name == short]

    def outline(self, rel_path: str) -> list[Symbol]:
        self.build()
        return sorted((s for s in self.symbols if s.path == rel_path), key=lambda s: s.line)
