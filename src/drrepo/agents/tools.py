"""Read-only LangChain tools that investigator agents can call, and `build_tools`.

Families (an analyst lists the ones it may use in `Analyst.tool_families`):

    files         read_file, list_directory, find_files, search_code
    scanners      run_scanner_on_path  (same wrappers as recon)
    dependencies  query_osv            (exact version; shared with the MCP server)
    git_history   get_file_git_history (GitHub API: shallow clones have one commit)
    symbols       find_definition, find_references, outline  (agents/symbols.py)

The LLM picks every argument, so every argument is hostile: paths go through
`resolve_safe_path`, globs may not contain `..`/absolute paths/drive letters,
regexes are length-capped, and all output is size-capped. No tool writes,
executes, or reaches arbitrary URLs. Symlinks were already neutralized at clone
time (`core.symlinks=false`) and resolution follows any that remain.
"""

from __future__ import annotations

import fnmatch
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import regex
from github import GithubException
from langchain_core.tools import tool

from drrepo.agents.symbols import NAME_RE, Symbol, SymbolIndex
from drrepo.config import Config
from drrepo.recon.dependencies import DependencyLookupCache, build_vulnerabilities, query_osv_ids
from drrepo.recon.files import SKIP_DIRS, iter_repo_files, read_text_file, relative_posix
from drrepo.recon.github import make_github_client
from drrepo.recon.manifests import normalize_pypi_name
from drrepo.recon.scanners import SCANNERS

# ---------------------------------------------------------------- files ---

MAX_READ_CHARS = 40_000
MAX_READ_FILE_BYTES = 2_000_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_MATCHES = 80
MAX_PATTERN_LENGTH = 300
MAX_SEARCH_LINE_CHARS = 2000
SEARCH_LINE_TIMEOUT_SECONDS = 0.05
SEARCH_TIME_BUDGET_SECONDS = 15.0


class PathEscapesSandboxError(ValueError):
    """A requested path would resolve outside the clone root (or is malformed)."""


def resolve_safe_path(root: Path, requested: str) -> Path:
    """Resolve `requested` under `root`, rejecting anything that escapes it."""
    root = root.resolve()
    if "\x00" in requested:
        raise PathEscapesSandboxError(f"Path {requested!r} is invalid (NUL byte)")
    try:
        candidate = (root / requested.strip()).resolve()
    except (ValueError, OSError) as e:
        raise PathEscapesSandboxError(f"Path {requested!r} is invalid: {e}") from e
    if candidate != root and root not in candidate.parents:
        raise PathEscapesSandboxError(f"Path {requested!r} escapes the repository root")
    return candidate


def _safe_glob(glob: str | None) -> str | None:
    if glob is None:
        return None
    glob = glob.strip()
    if (
        not glob
        or ".." in glob.replace("\\", "/").split("/")
        or glob.startswith(("/", "\\"))
        or ":" in glob
    ):
        raise PathEscapesSandboxError(
            f"Glob {glob!r} must be a relative pattern like '*.py' or 'src/**/*.ts'"
        )
    return glob


def _matches(rel: str, glob: str) -> bool:
    return fnmatch.fnmatch(rel, glob) or (
        "/" not in glob and fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob)
    )


def make_file_tools(clone_root: str) -> list[Any]:
    root = Path(clone_root).resolve()

    @tool
    def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Read a text file from the repository, optionally a 1-indexed inclusive line range.

        Args:
            path: File path relative to the repository root, e.g. "src/app/main.py".
            start_line: First line to include (optional).
            end_line: Last line to include (optional).
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.is_file():
            return f"ERROR: '{path}' is not a file (use list_directory or find_files)"
        try:
            size = target.stat().st_size
        except OSError as e:
            return f"ERROR: could not stat '{path}': {e}"
        if size > MAX_READ_FILE_BYTES:
            return f"ERROR: '{path}' is {size:,} bytes, too large; use search_code instead"
        text = read_text_file(target)
        if text is None:
            return f"ERROR: '{path}' looks like a binary file"

        lines = text.splitlines()
        if start_line or end_line:
            start = max((start_line or 1) - 1, 0)
            end = min(end_line or len(lines), len(lines))
            selected = lines[start:end]
            first = start + 1
        else:
            selected, first = lines, 1
        body = "\n".join(f"{n:>5}| {line}" for n, line in enumerate(selected, start=first))
        if len(body) > MAX_READ_CHARS:
            body = (
                body[:MAX_READ_CHARS]
                + f"\n... [truncated; file has {len(lines)} lines, use start_line/end_line]"
            )
        return body or "(empty file)"

    @tool
    def list_directory(path: str = ".") -> str:
        """List files and subdirectories at a path in the repository.

        Args:
            path: Directory relative to the repository root; "." is the root.
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.is_dir():
            return f"ERROR: '{path}' is not a directory"
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for entry in entries[:MAX_LIST_ENTRIES]:
            rel = relative_posix(entry, root)
            if entry.is_dir():
                lines.append(
                    f"dir   {rel}/"
                    + ("  (vendored/build, skipped by search)" if entry.name in SKIP_DIRS else "")
                )
            else:
                try:
                    lines.append(f"file  {rel}  ({entry.stat().st_size:,} bytes)")
                except OSError:
                    lines.append(f"file  {rel}")
        if len(entries) > MAX_LIST_ENTRIES:
            lines.append(f"... and {len(entries) - MAX_LIST_ENTRIES} more entries")
        return "\n".join(lines) or "(empty directory)"

    @tool
    def find_files(glob: str) -> str:
        """Find files by path pattern, e.g. "*.py", "**/test_*.py", ".github/workflows/*".

        Args:
            glob: fnmatch-style pattern matched against repo-relative paths (and bare filenames).
        """
        try:
            pattern = _safe_glob(glob)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if pattern is None:
            return "ERROR: a glob pattern is required"
        matches = []
        for path in iter_repo_files(root, max_bytes=None):
            rel = relative_posix(path, root)
            if _matches(rel, pattern):
                matches.append(rel)
                if len(matches) >= MAX_LIST_ENTRIES:
                    matches.append("... [truncated]")
                    break
        return "\n".join(matches) or "No files matched"

    @tool
    def search_code(pattern: str, glob: str | None = None, ignore_case: bool = False) -> str:
        """Search repository file contents for a Python regular expression.

        Args:
            pattern: Regular expression, e.g. "subprocess\\.(run|Popen)".
            glob: Optional path pattern to restrict the search, e.g. "*.py".
            ignore_case: Case-insensitive match.
        """
        if len(pattern) > MAX_PATTERN_LENGTH:
            return f"ERROR: pattern longer than {MAX_PATTERN_LENGTH} characters"
        try:
            compiled = regex.compile(pattern, regex.IGNORECASE if ignore_case else 0)
            file_glob = _safe_glob(glob)
        except regex.error as e:
            return f"ERROR: invalid regex: {e}"
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"

        # The pattern is LLM-chosen (and so steerable by prompt injection in the
        # analyzed repo). Stdlib `re` can't be interrupted, so a catastrophic-
        # backtracking pattern would spin a thread forever; `regex` matches with
        # a timeout, and the whole search has a wall-clock budget.
        deadline = time.monotonic() + SEARCH_TIME_BUDGET_SECONDS
        matches: list[str] = []
        for path in iter_repo_files(root):
            rel = relative_posix(path, root)
            if file_glob and not _matches(rel, file_glob):
                continue
            text = read_text_file(path)
            if text is None:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if len(line) > MAX_SEARCH_LINE_CHARS:
                    continue
                try:
                    hit = compiled.search(line, timeout=SEARCH_LINE_TIMEOUT_SECONDS)
                except TimeoutError:
                    return "ERROR: pattern is too slow (catastrophic backtracking); simplify it"
                if hit:
                    matches.append(f"{rel}:{line_no}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        return "\n".join(matches) + "\n... [truncated: narrow the pattern or glob]"
            if time.monotonic() > deadline:
                partial = "\n".join(matches) or "No matches so far"
                return partial + "\n... [stopped: search time budget used; narrow the glob]"
        return "\n".join(matches) or "No matches found"

    return [read_file, list_directory, find_files, search_code]


# ------------------------------------------------------------- scanners ---

MAX_FINDINGS_SHOWN = 40


def make_scan_tools(clone_root: str, config: Config) -> list[Any]:
    root = Path(clone_root).resolve()

    @tool
    def run_scanner_on_path(scanner: str, path: str = ".") -> str:
        """Re-run a static analysis tool on one file or directory for a closer look.

        Args:
            scanner: "ruff" (Python bugs/lint), "bandit" (Python security), or "semgrep" (multi-language security).
            path: File or directory relative to the repository root.
        """
        if scanner not in SCANNERS:
            return f"ERROR: unknown scanner '{scanner}'. Choose from: {sorted(SCANNERS)}"
        if scanner == "semgrep" and not config.enable_semgrep:
            return "semgrep is disabled by configuration"
        if scanner == "bandit" and not config.enable_bandit:
            return "bandit is disabled by configuration"
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: '{path}' does not exist"

        result = SCANNERS[scanner](root, target, timeout=config.collector_timeout_seconds)
        if not result.available:
            return f"{scanner} unavailable: {result.reason}"
        if not result.findings:
            return f"{scanner} found no issues in '{path}'"
        lines = [
            f"{f['file']}:{f.get('line')}: [{f.get('severity') or '-'}] {f.get('rule')}: {f.get('message', '')[:200]}"
            for f in result.findings[:MAX_FINDINGS_SHOWN]
        ]
        if len(result.findings) > MAX_FINDINGS_SHOWN:
            lines.append(f"... and {len(result.findings) - MAX_FINDINGS_SHOWN} more")
        return "\n".join(lines)

    return [run_scanner_on_path]


# --------------------------------------------------------- dependencies ---

ECOSYSTEMS = {
    "pypi": "PyPI",
    "npm": "npm",
    "go": "Go",
    "crates.io": "crates.io",
    "maven": "Maven",
    "rubygems": "RubyGems",
    "nuget": "NuGet",
    "packagist": "Packagist",
}


def lookup_package(
    package: str,
    ecosystem: str,
    version: str,
    config: Config,
    cache: DependencyLookupCache | None = None,
) -> str:
    """Human/LLM-readable OSV result for one package version (shared with the MCP server)."""
    eco = ECOSYSTEMS.get(ecosystem.strip().lower(), ecosystem.strip())
    name = normalize_pypi_name(package) if eco == "PyPI" else package.strip()
    version = version.strip().lstrip("v=")
    if not name or not version:
        return "ERROR: package and an exact version are required"
    pkg = (eco, name, version)
    try:
        with httpx.Client(
            timeout=config.collector_timeout_seconds, headers={"User-Agent": "drrepo"}
        ) as client:
            ids = query_osv_ids(client, [pkg], cache)
            vulns = build_vulnerabilities(client, ids, cache)
    except (httpx.HTTPError, ValueError) as e:
        return f"ERROR: OSV.dev lookup failed: {e}"
    if not vulns:
        return f"No known vulnerabilities for {name}@{version} ({eco})"
    return "\n".join(
        f"{v['vuln_id']} [{v.get('severity') or 'unrated'}] {v.get('summary') or ''}"
        + (f" | fixed in: {', '.join(v['fixed_versions'])}" if v.get("fixed_versions") else "")
        + f" | https://osv.dev/vulnerability/{v['vuln_id']}"
        for v in vulns
    )


def make_dependency_tools(config: Config, cache: DependencyLookupCache | None = None) -> list[Any]:
    lookup_cache = cache if config.enable_dependency_lookup_cache else None

    @tool
    def query_osv(package: str, ecosystem: str, version: str) -> str:
        """Look up known vulnerabilities (with severity and fixed versions) for one exact package version.

        Args:
            package: Package name, e.g. "requests".
            ecosystem: "PyPI", "npm", "Go", "crates.io", "Maven", "RubyGems", "NuGet", or "Packagist".
            version: Exact version, e.g. "2.25.0" (not a range).
        """
        return lookup_package(package, ecosystem, version, config, lookup_cache)

    return [query_osv]


# ---------------------------------------------------------- git history ---

MAX_COMMITS = 10


def make_git_history_tools(repo_full_name: str, config: Config) -> list[Any]:
    lock = threading.Lock()
    state: dict[str, Any] = {}

    def _repo() -> Any:
        with lock:
            if "repo" not in state:
                state["repo"] = make_github_client(config.github_token).get_repo(repo_full_name)
            return state["repo"]

    @tool
    def get_file_git_history(path: str) -> str:
        """Show the most recent commits that touched a file (sha, date, author, message).

        Args:
            path: File path relative to the repository root, e.g. "src/auth.py".
        """
        clean = path.strip().removeprefix("./")
        if not clean or ".." in clean.split("/"):
            return "ERROR: give a repository-relative file path"
        try:
            lines = []
            for commit in _repo().get_commits(path=clean)[:MAX_COMMITS]:
                author = commit.commit.author
                when = author.date.date().isoformat() if author and author.date else "?"
                who = author.name if author else "unknown"
                message = (
                    (commit.commit.message or "").splitlines()[0][:100]
                    if commit.commit.message
                    else ""
                )
                lines.append(f"{commit.sha[:7]} {when} {who}: {message}")
        except GithubException as e:
            return f"ERROR: GitHub API error ({e.status})"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        return "\n".join(lines) or f"No commit history found for '{clean}'"

    return [get_file_git_history]


# ------------------------------------------------------------- registry ---

# -------------------------------------------------------------- symbols ---

MAX_DEFINITIONS_SHOWN = 20
MAX_REFERENCES_SHOWN = 40
MAX_OUTLINE_ENTRIES = 150
REFERENCE_TIME_BUDGET_SECONDS = 10.0


def _symbol_line(s: Symbol) -> str:
    span = f"{s.line}-{s.end_line}" if s.end_line and s.end_line != s.line else str(s.line)
    return f"{s.path}:{span}: {s.kind} {s.name}: {s.signature}"


def make_symbol_tools(clone_root: str, index: SymbolIndex | None = None) -> list[Any]:
    """Symbol tools over `index` (built lazily on first use; pass the run's shared one)."""
    root = Path(clone_root).resolve()
    symbols = index or SymbolIndex(root)

    def _note() -> str:
        return f"\n(index incomplete: {symbols.truncated})" if symbols.truncated else ""

    @tool
    def find_definition(name: str) -> str:
        """Where a function, method, class or type is defined: file, line range and signature.

        Args:
            name: The symbol name, e.g. "authenticate" or "UserService.login".
        """
        if not NAME_RE.match(name.strip()):
            return "ERROR: name must be an identifier, optionally dotted (e.g. 'Class.method')"
        found = symbols.definitions(name.strip())
        if not found:
            return (
                f"No definition of {name!r} found in {len(symbols.files)} indexed files.{_note()}"
            )
        lines = [_symbol_line(s) for s in found[:MAX_DEFINITIONS_SHOWN]]
        if len(found) > MAX_DEFINITIONS_SHOWN:
            lines.append(f"... and {len(found) - MAX_DEFINITIONS_SHOWN} more")
        return "\n".join(lines) + _note()

    @tool
    def find_references(name: str, glob: str | None = None) -> str:
        """Lines that mention a symbol by name (whole word), definitions excluded.

        Matches by name only (no import or scope resolution), so treat results as leads.

        Args:
            name: The symbol name; for "Class.method" the final segment is searched.
            glob: Optional file filter, e.g. "src/**/*.py".
        """
        if not NAME_RE.match(name.strip()):
            return "ERROR: name must be an identifier, optionally dotted (e.g. 'Class.method')"
        try:
            glob = _safe_glob(glob)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        short = name.strip().rsplit(".", 1)[-1]
        word = regex.compile(rf"(?<![\w$]){regex.escape(short)}(?![\w$])")
        definitions = {(s.path, s.line) for s in symbols.definitions(short)}
        started = time.monotonic()
        hits: list[str] = []
        for rel in symbols.build().files:
            if glob and not _matches(rel, glob):
                continue
            if time.monotonic() - started > REFERENCE_TIME_BUDGET_SECONDS:
                hits.append("... stopped: time budget reached")
                break
            text = read_text_file(root / rel) or ""
            if short not in text:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if (rel, number) in definitions or short not in line:
                    continue
                if word.search(line[:MAX_SEARCH_LINE_CHARS]):
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                    if len(hits) >= MAX_REFERENCES_SHOWN:
                        return (
                            "\n".join(hits) + f"\n... stopped at {MAX_REFERENCES_SHOWN} references"
                        )
        return ("\n".join(hits) or f"No references to {short!r} outside its definitions.") + _note()

    @tool
    def outline(path: str) -> str:
        """The classes, functions and methods defined in one source file, with line ranges.

        Args:
            path: File path relative to the repository root, e.g. "src/app/auth.py".
        """
        try:
            target = resolve_safe_path(root, path)
        except PathEscapesSandboxError as e:
            return f"ERROR: {e}"
        rel = relative_posix(target, root)
        entries = symbols.outline(rel)
        if not entries:
            if rel not in symbols.build().files:
                return f"'{path}' is not an indexed source file (use read_file)."
            return f"No definitions found in '{rel}'."
        lines = [
            f"{'  ' * s.name.count('.')}{_symbol_line(s)}" for s in entries[:MAX_OUTLINE_ENTRIES]
        ]
        if len(entries) > MAX_OUTLINE_ENTRIES:
            lines.append(f"... and {len(entries) - MAX_OUTLINE_ENTRIES} more")
        return "\n".join(lines)

    return [find_definition, find_references, outline]


TOOL_FAMILIES = ("files", "scanners", "dependencies", "git_history", "symbols")


def build_tools(
    families: tuple[str, ...] | list[str],
    *,
    clone_root: str | None,
    config: Config,
    cache: DependencyLookupCache | None = None,
    repo_full_name: str | None = None,
    symbol_index: SymbolIndex | None = None,
) -> list[Any]:
    """LangChain tools for the requested families.

    Families that need something unavailable are silently omitted (no clone ->
    no file/scanner tools; no `owner/repo` -> no git history), so the agent is
    only ever offered tools that can work.
    """
    unknown = set(families) - set(TOOL_FAMILIES)
    if unknown:
        raise ValueError(f"Unknown tool families: {sorted(unknown)}")

    tools: list[Any] = []
    if "files" in families and clone_root:
        tools += make_file_tools(clone_root)
    if "scanners" in families and clone_root:
        tools += make_scan_tools(clone_root, config)
    if "dependencies" in families:
        tools += make_dependency_tools(config, cache)
    if "git_history" in families and repo_full_name:
        tools += make_git_history_tools(repo_full_name, config)
    if "symbols" in families and clone_root:
        tools += make_symbol_tools(clone_root, symbol_index)
    return tools
