"""Dependency manifest and lockfile parsing. Pure text-in, packages-out.

Exact versions only. An `==` pin or a lockfile entry is auditable; a range like
`requests>=2.6` says nothing about what actually gets installed, so querying
OSV for its lower bound would report vulnerabilities the project may not have.
Ranges are recorded as `unpinned` so the analyst can flag the missing lockfile.

Lockfiles win: in a directory with `uv.lock`/`poetry.lock`/`package-lock.json`,
the resolved versions replace that ecosystem's manifests.

Dev vs. runtime: each package is also classified as development-only or not
(dependency groups, `devDependencies`, `requirements-dev.txt`, package-lock's
`dev` flag, and for `uv.lock` the transitive closure of the project's runtime
dependencies). A vulnerable test runner matters far less than a vulnerable
runtime dependency, and the analyst weighs them accordingly.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drrepo.recon.files import iter_repo_files, read_text_file

Package = tuple[str, str, str]  # (ecosystem, name, version)

# `name[extra1,extra2] == 1.2.3 ; marker`
_PEP508_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?P<spec>[^;#]*)"
)
_EXACT_RE = re.compile(r"^\s*===?\s*(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)\s*$")
_NPM_EXACT_RE = re.compile(r"^=?v?(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$")
_POETRY_EXACT_RE = re.compile(r"^=?=?\s*(?P<version>\d[\w.+-]*)$")

MAX_MANIFESTS_PER_TYPE = 5


@dataclass
class ParsedDeps:
    packages: list[Package] = field(default_factory=list)
    dev: set[Package] = field(default_factory=set)
    unpinned: list[str] = field(default_factory=list)

    def add(self, pkg: Package, *, dev: bool = False) -> None:
        self.packages.append(pkg)
        if dev:
            self.dev.add(pkg)

    def extend(self, other: ParsedDeps) -> None:
        self.packages.extend(other.packages)
        self.dev |= other.dev
        self.unpinned.extend(other.unpinned)


def normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pep508(requirement: str) -> tuple[str, str | None] | None:
    """(normalized_name, exact_version_or_None), or None if not a registry requirement."""
    req = requirement.strip()
    if not req or req.startswith(("-", "git+", "http://", "https://", "file:")) or " @ " in req:
        return None
    m = _PEP508_RE.match(req)
    if not m:
        return None
    exact = _EXACT_RE.match(m.group("spec"))
    return normalize_pypi_name(m.group("name")), exact.group("version") if exact else None


def _collect_pep508(deps: ParsedDeps, requirements: list[str], *, dev: bool) -> None:
    for req in requirements:
        parsed = _parse_pep508(req)
        if parsed is None:
            continue
        name, version = parsed
        if version:
            deps.add(("PyPI", name, version), dev=dev)
        else:
            deps.unpinned.append(name)


def parse_requirements_txt(text: str, *, dev: bool = False) -> ParsedDeps:
    deps = ParsedDeps()
    lines = [raw.split(" #", 1)[0].strip() for raw in text.splitlines()]
    _collect_pep508(deps, [line for line in lines if line and not line.startswith("#")], dev=dev)
    return deps


def parse_requirements_dev_txt(text: str) -> ParsedDeps:
    return parse_requirements_txt(text, dev=True)


def parse_pyproject_toml(text: str) -> ParsedDeps:
    deps = ParsedDeps()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return deps

    project = data.get("project", {}) or {}
    _collect_pep508(deps, list(project.get("dependencies") or []), dev=False)
    for extra in (project.get("optional-dependencies") or {}).values():
        _collect_pep508(deps, list(extra), dev=False)  # extras ship to users
    for group in (data.get("dependency-groups") or {}).values():
        _collect_pep508(deps, [r for r in group if isinstance(r, str)], dev=True)

    # Poetry `[tool.poetry.*dependencies]`: only bare "1.2.3" strings are exact pins.
    poetry = data.get("tool", {}).get("poetry", {}) or {}
    tables: list[tuple[dict[str, Any], bool]] = [
        (poetry.get("dependencies") or {}, False),
        (poetry.get("dev-dependencies") or {}, True),
    ]
    tables += [
        ((g or {}).get("dependencies") or {}, True) for g in (poetry.get("group") or {}).values()
    ]
    for table, is_dev in tables:
        for name, spec in table.items():
            if name.lower() == "python":
                continue
            version = spec if isinstance(spec, str) else (spec or {}).get("version")
            m = _POETRY_EXACT_RE.match(version.strip()) if isinstance(version, str) else None
            if m:
                deps.add(("PyPI", normalize_pypi_name(name), m.group("version")), dev=is_dev)
            else:
                deps.unpinned.append(normalize_pypi_name(name))
    return deps


def parse_package_json(text: str) -> ParsedDeps:
    deps = ParsedDeps()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return deps
    for section, is_dev in (
        ("dependencies", False),
        ("optionalDependencies", False),
        ("devDependencies", True),
    ):
        for name, spec in (data.get(section) or {}).items():
            m = _NPM_EXACT_RE.match(str(spec).strip())
            if m:
                deps.add(("npm", name, m.group("version")), dev=is_dev)
            else:
                deps.unpinned.append(name)
    return deps


def _dep_names(entries: Any) -> list[str]:
    return [
        normalize_pypi_name(e["name"])
        for e in entries or []
        if isinstance(e, dict) and e.get("name")
    ]


def parse_uv_lock(text: str) -> ParsedDeps:
    """`uv.lock`: runtime = transitive closure of the workspace packages' runtime deps."""
    deps = ParsedDeps()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return deps

    packages = [p for p in data.get("package", []) or [] if p.get("name")]
    graph: dict[str, list[str]] = {}
    roots: list[str] = []
    for pkg in packages:
        name = normalize_pypi_name(pkg["name"])
        children = _dep_names(pkg.get("dependencies"))
        for extra in (pkg.get("optional-dependencies") or {}).values():
            children += _dep_names(extra)
        graph.setdefault(name, []).extend(children)
        source = pkg.get("source") or {}
        if source.get("editable") or source.get("virtual"):
            roots.append(name)

    runtime: set[str] = set()
    queue = deque(child for root in roots for child in graph.get(root, []))
    while queue:
        name = queue.popleft()
        if name not in runtime:
            runtime.add(name)
            queue.extend(graph.get(name, []))

    for pkg in packages:
        source = pkg.get("source") or {}
        if source.get("editable") or source.get("virtual") or not pkg.get("version"):
            continue  # the project itself / workspace members
        name = normalize_pypi_name(pkg["name"])
        deps.add(("PyPI", name, str(pkg["version"])), dev=bool(roots) and name not in runtime)
    return deps


def parse_poetry_lock(text: str) -> ParsedDeps:
    deps = ParsedDeps()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return deps
    for pkg in data.get("package", []) or []:
        if pkg.get("name") and pkg.get("version"):
            # `category` exists in Poetry < 1.2 lockfiles only; newer ones can't be classified.
            deps.add(
                ("PyPI", normalize_pypi_name(pkg["name"]), str(pkg["version"])),
                dev=pkg.get("category") == "dev",
            )
    return deps


def parse_package_lock_json(text: str) -> ParsedDeps:
    deps = ParsedDeps()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return deps
    packages = data.get("packages")
    if isinstance(packages, dict):  # lockfileVersion 2/3
        for path, meta in packages.items():
            if (
                not path
                or not isinstance(meta, dict)
                or meta.get("link")
                or not meta.get("version")
            ):
                continue
            name = meta.get("name") or path.rsplit("node_modules/", 1)[-1]
            deps.add(("npm", name, meta["version"]), dev=bool(meta.get("dev")))
    else:  # lockfileVersion 1
        for name, meta in (data.get("dependencies") or {}).items():
            if isinstance(meta, dict) and meta.get("version"):
                deps.add(("npm", name, meta["version"]), dev=bool(meta.get("dev")))
    return deps


MANIFEST_PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "requirements-dev.txt": parse_requirements_dev_txt,
    "pyproject.toml": parse_pyproject_toml,
    "package.json": parse_package_json,
}
LOCKFILE_PARSERS = {
    "uv.lock": parse_uv_lock,
    "poetry.lock": parse_poetry_lock,
    "package-lock.json": parse_package_lock_json,
}
_PY_LOCKS = {"uv.lock", "poetry.lock"}
_PY_MANIFESTS = {"requirements.txt", "requirements-dev.txt", "pyproject.toml"}


def discover(root: Path) -> tuple[ParsedDeps, list[str]]:
    """Parse every supported manifest/lockfile under `root`.

    Returns (deduplicated deps, repo-relative files used). A package is dev-only
    if every occurrence of it was classified dev.
    """
    by_dir: dict[Path, dict[str, Path]] = {}
    counts: dict[str, int] = {}
    wanted = set(MANIFEST_PARSERS) | set(LOCKFILE_PARSERS)
    for path in iter_repo_files(root, max_bytes=20_000_000):
        if path.name not in wanted or counts.get(path.name, 0) >= MAX_MANIFESTS_PER_TYPE:
            continue
        counts[path.name] = counts.get(path.name, 0) + 1
        by_dir.setdefault(path.parent, {})[path.name] = path

    combined = ParsedDeps()
    runtime_seen: set[Package] = set()
    used: list[str] = []
    for files in by_dir.values():
        has_py_lock = bool(_PY_LOCKS & files.keys())
        has_npm_lock = "package-lock.json" in files
        for filename, path in sorted(files.items()):
            if (has_py_lock and filename in _PY_MANIFESTS) or (
                has_npm_lock and filename == "package.json"
            ):
                continue
            text = read_text_file(path)
            if text is None:
                continue
            parser = LOCKFILE_PARSERS.get(filename) or MANIFEST_PARSERS[filename]
            parsed = parser(text)
            runtime_seen |= set(parsed.packages) - parsed.dev
            combined.extend(parsed)
            used.append(path.relative_to(root).as_posix())

    unique = list(dict.fromkeys(combined.packages))
    pinned_names = {name for _, name, _ in unique}
    return (
        ParsedDeps(
            packages=unique,
            dev={p for p in combined.dev if p not in runtime_seen},
            unpinned=sorted({n for n in combined.unpinned if n not in pinned_names}),
        ),
        used,
    )
