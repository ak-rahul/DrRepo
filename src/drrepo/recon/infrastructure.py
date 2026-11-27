"""CI workflow and container security for the analyzed repository.

Supply-chain risk often lives outside the source code, in GitHub Actions
workflows (template injection, `pull_request_target` checking out PR code,
unpinned third-party actions, overly broad tokens) and in Dockerfiles (root
containers, unpinned base images, secrets in build arguments).

Tools, all parse-only:
- **zizmor** audits `.github/workflows/`, composite actions, and Dependabot config
  (`--offline`: no network; `--no-config --no-ignores`: the analyzed repository's
  own config and ignore comments can't silence findings, like ruff `--isolated`);
- **hadolint** lints Dockerfiles. It runs from a neutral working directory with
  `--disable-ignore-pragma`, so neither a repo `.hadolint.yaml` nor inline
  ignores apply;
- a built-in check flags Dockerfiles whose final stage never drops root.

data:
    findings: [{tool, rule, message, severity, file, line, url, category}]
        severity is a DrRepo level (critical/high/medium/low); category is the
        report category that should score it ("security" or "maintainability")
    workflow_files: int, dockerfiles: [str]
    tool_status: {zizmor, hadolint, dockerfile_checks: "ok" | "skipped: ..." | "disabled by config"}
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from drrepo.config import Config
from drrepo.models import CollectorResult, CollectorStatus
from drrepo.recon.files import iter_repo_files, read_text_file, relative_posix
from drrepo.recon.scanners import find_executable

NAME = "infrastructure"

# zizmor severity -> DrRepo severity. zizmor rates hardening advice (unpinned
# actions, broad permissions) as high; for a repository audit that is one level
# lower than a directly exploitable flaw. Only these audits keep zizmor's rating:
_ZIZMOR_EXPLOITABLE = {
    "template-injection",
    "dangerous-triggers",
    "github-env",
    "known-vulnerable-actions",
    "bot-conditions",
    "unsound-contains",
    "impostor-commit",
    "ref-confusion",
    "overprovisioned-secrets",
    "secrets-inherit",
    "unredacted-secrets",
    "self-hosted-runner",
}
_ZIZMOR_SEVERITY = {"high": "high", "medium": "medium", "low": "low", "informational": "low"}
_ONE_LEVEL_DOWN = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}
# hadolint levels worth reporting; "info" and "style" are noise for an audit.
_HADOLINT_SEVERITY = {"error": "medium", "warning": "low"}
# hadolint rules that are about security rather than image hygiene.
_HADOLINT_SECURITY_RULES = {"DL3002", "DL3004", "DL3020", "DL3064"}
# hadolint reports these as warnings; for an audit they matter more than hygiene.
_HADOLINT_ELEVATED = {"DL3064": "medium", "DL3002": "medium"}  # secrets in ARG/ENV, root USER
_DOCKERFILE_RE = re.compile(r"(^|[._-])dockerfile([._-]|$)|\.dockerfile$", re.IGNORECASE)
_MAX_FINDINGS = 300


def is_dockerfile(name: str) -> bool:
    return name.lower() == "dockerfile" or bool(_DOCKERFILE_RE.search(name))


def _run_json(argv: list[str], cwd: Path, timeout: int) -> tuple[Any | None, str | None]:
    """Run a linter that prints JSON; returns (parsed, error_reason). Non-zero exits are fine:
    both tools exit non-zero when they find something."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    except OSError as e:
        return None, f"could not run: {e}"
    try:
        return json.loads(proc.stdout or "[]"), None
    except json.JSONDecodeError:
        return None, f"unparseable output (exit {proc.returncode}): {proc.stderr.strip()[:200]}"


def run_zizmor(root: Path, timeout: int) -> tuple[list[dict[str, Any]], str]:
    exe = find_executable("zizmor")
    if exe is None:
        return [], "skipped: zizmor not installed"
    argv = [exe, "--offline", "--no-config", "--no-ignores", "--format", "json", "--", str(root)]
    parsed, error = _run_json(argv, cwd=root, timeout=timeout)
    if error:
        return [], f"skipped: {error}"
    findings = []
    for raw in parsed or []:
        determinations = raw.get("determinations", {})
        severity = _ZIZMOR_SEVERITY.get(str(determinations.get("severity", "")).lower(), "low")
        if raw.get("ident") not in _ZIZMOR_EXPLOITABLE:
            severity = _ONE_LEVEL_DOWN[severity]
        if str(determinations.get("confidence", "")).lower() == "low":
            severity = _ONE_LEVEL_DOWN[severity]
        primary = next(
            (
                loc
                for loc in raw.get("locations", [])
                if loc.get("symbolic", {}).get("kind") == "Primary"
            ),
            (raw.get("locations") or [{}])[0],
        )
        path = (primary.get("symbolic", {}).get("key", {}).get("Local", {}) or {}).get(
            "verbatim_path", ""
        )
        row = primary.get("concrete", {}).get("location", {}).get("start_point", {}).get("row")
        annotation = primary.get("symbolic", {}).get("annotation") or ""
        findings.append(
            {
                "tool": "zizmor",
                "rule": raw.get("ident", "unknown"),
                "message": raw.get("desc", "") + (f": {annotation}" if annotation else ""),
                "severity": severity,
                "file": relative_posix(path, root) if path else None,
                "line": row + 1 if isinstance(row, int) else None,  # zizmor rows are 0-based
                "url": raw.get("url"),
                "category": "security",
            }
        )
    return findings, "ok"


def run_hadolint(
    root: Path, dockerfiles: list[Path], timeout: int
) -> tuple[list[dict[str, Any]], str]:
    exe = find_executable("hadolint")
    if exe is None:
        return [], "skipped: hadolint not installed"
    findings = []
    # A neutral working directory: hadolint would otherwise pick up a repo's .hadolint.yaml.
    with tempfile.TemporaryDirectory(prefix="drrepo_hadolint_") as neutral:
        argv = [exe, "--no-fail", "--disable-ignore-pragma", "-f", "json", *map(str, dockerfiles)]
        parsed, error = _run_json(argv, cwd=Path(neutral), timeout=timeout)
    if error:
        return [], f"skipped: {error}"
    for raw in parsed or []:
        severity = _HADOLINT_SEVERITY.get(str(raw.get("level", "")).lower())
        if severity is None:
            continue
        code = raw.get("code", "unknown")
        if code in _HADOLINT_ELEVATED:
            severity = _HADOLINT_ELEVATED[code]
        findings.append(
            {
                "tool": "hadolint",
                "rule": code,
                "message": raw.get("message", ""),
                "severity": severity,
                "file": relative_posix(raw.get("file", ""), root),
                "line": raw.get("line"),
                "url": f"https://github.com/hadolint/hadolint/wiki/{code}"
                if code.startswith("DL")
                else None,
                "category": "security" if code in _HADOLINT_SECURITY_RULES else "maintainability",
            }
        )
    return findings, "ok"


def check_dockerfile_user(root: Path, dockerfile: Path) -> dict[str, Any] | None:
    """Flag a Dockerfile whose final stage never switches away from root."""
    text = read_text_file(dockerfile) or ""
    instructions = [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    stages = [i for i, (_, line) in enumerate(instructions) if line.upper().startswith("FROM ")]
    if not stages:
        return None
    final = instructions[stages[-1] :]
    users = [
        line.split(None, 1)[1].strip() if " " in line else ""
        for _, line in final
        if line.upper().startswith("USER ")
    ]
    if users and users[-1].split(":")[0] not in ("root", "0"):
        return None
    return {
        "tool": "drrepo",
        "rule": "container-runs-as-root",
        "message": "The final image stage never sets a non-root USER, so the container runs as root",
        "severity": "medium",
        "file": relative_posix(dockerfile, root),
        "line": final[0][0],
        "url": None,
        "category": "security",
    }


def collect_infrastructure(clone_path: str, config: Config) -> CollectorResult:
    # Absolute: hadolint runs from a neutral directory, where relative paths wouldn't resolve.
    root = Path(clone_path).resolve()
    if not root.is_dir():
        return CollectorResult.skipped(NAME, "no clone")
    workflows = root / ".github" / "workflows"
    workflow_files = (
        [p for p in workflows.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file()]
        if workflows.is_dir()
        else []
    )
    dockerfiles = [p for p in iter_repo_files(root) if is_dockerfile(p.name)]

    findings: list[dict[str, Any]] = []
    status: dict[str, str] = {}
    if not config.enable_workflow_audit:
        status["zizmor"] = "disabled by config"
    elif not workflow_files and not (root / "action.yml").is_file():
        status["zizmor"] = "skipped: no GitHub Actions workflows"
    else:
        found, status["zizmor"] = run_zizmor(root, config.collector_timeout_seconds)
        findings += found

    if not config.enable_dockerfile_audit:
        status["hadolint"] = status["dockerfile_checks"] = "disabled by config"
    elif not dockerfiles:
        status["hadolint"] = status["dockerfile_checks"] = "skipped: no Dockerfiles"
    else:
        found, status["hadolint"] = run_hadolint(
            root, dockerfiles, config.collector_timeout_seconds
        )
        findings += found
        findings += [f for d in dockerfiles if (f := check_dockerfile_user(root, d))]
        status["dockerfile_checks"] = "ok"

    return CollectorResult(
        name=NAME,
        status=CollectorStatus.OK,
        data={
            "findings": findings[:_MAX_FINDINGS],
            "workflow_files": len(workflow_files),
            "dockerfiles": [relative_posix(d, root) for d in dockerfiles],
            "tool_status": status,
        },
    )
