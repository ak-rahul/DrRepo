"""`drrepo` command-line interface.

    drrepo analyze <url> [--shallow] [--format json,md,sarif] [--fail-under N] ...
    drrepo ui          [--port 8501]          Streamlit web UI
    drrepo mcp         [--transport stdio]    Model Context Protocol server
    drrepo health      [--json]               connectivity of LLM provider, GitHub, OSV.dev
    drrepo doctor                             full local diagnostics
    drrepo health-api  [--port 8000]          FastAPI health endpoint

`drrepo <url>` is shorthand for `drrepo analyze <url>`.

Exit codes: 0 success, 1 runtime error, 2 usage/config error, 3 score below --fail-under.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from drrepo import __version__
from drrepo.config import Config
from drrepo.core.errors import ConfigurationError
from drrepo.core.log import configure_logging, logger
from drrepo.report.exporters import FORMATS

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_FAIL_UNDER = 0, 1, 2, 3
SUBCOMMANDS = {"analyze", "ui", "mcp", "health", "doctor", "health-api"}


def _load_config(env_file: str | None) -> Config:
    return Config.from_env(env_file=env_file or None)


# ---------------------------------------------------------------- output ---


def print_summary(report: dict[str, Any], top: int = 10) -> None:
    from drrepo.report.synthesizer import grade

    repo = report.get("repository", {})
    score = float(report.get("overall_score", 0))
    width = 78
    print("\n" + "=" * width)
    print(f" DrRepo report: {repo.get('full_name') or repo.get('name', 'Unknown')}")
    print("=" * width)
    print(f" URL:      {repo.get('url', 'n/a')}")
    print(f" Score:    {score:.1f}/100  (grade {grade(score)})")
    history = report.get("score_history")
    if history:
        delta = history["overall_score_delta"]
        print(f" Trend:    {delta:+.1f} since {history['previous_timestamp'][:10]}")
    counts = report.get("issue_counts", {})
    print(" Issues:   " + ", ".join(f"{n} {sev}" for sev, n in counts.items()))

    print("\n Categories")
    for name, cs in report.get("category_scores", {}).items():
        shown = f"{cs['score']:5.1f}" if cs.get("assessed", True) else "  n/a"
        depth = " [deep]" if cs.get("investigation_depth") == "deep" else ""
        print(f"   {name.replace('_', ' ').title():<18}{shown}{depth}")
        for note in cs.get("notes", []):
            print(f"      note: {note}")

    deep = {
        n: cs
        for n, cs in report.get("category_scores", {}).items()
        if cs.get("investigation_trace")
    }
    if deep:
        print("\n How it investigated")
        for name, cs in deep.items():
            print(f"   {name.replace('_', ' ').title()}:")
            for call in cs["investigation_trace"]:
                print(f"     -> {call['tool']}({json.dumps(call['tool_input'])[:90]})")

    issues = report.get("issues", [])
    print(f"\n Top issues ({min(top, len(issues))} of {len(issues)})")
    for i, issue in enumerate(issues[:top], 1):
        where = (
            f" ({issue['file']}" + (f":{issue['line']}" if issue.get("line") else "") + ")"
            if issue.get("file")
            else ""
        )
        times = f" x{issue['occurrences']}" if issue.get("occurrences", 1) > 1 else ""
        print(f"  {i:>2}. [{issue['severity'].upper():<8}] {issue['title']}{times}{where}")
        print(f"      -> {issue['recommendation']}")
    if not issues:
        print("   No issues found.")
    print("=" * width + "\n")


# -------------------------------------------------------------- commands ---


def cmd_analyze(args: argparse.Namespace) -> int:
    from drrepo.service import AnalysisService, save_report

    config = _load_config(args.env_file)
    if args.shallow:
        config.enable_deep_investigation = False
    if args.no_history:
        config.enable_score_history = False
    configure_logging(
        config.log_level,
        log_file=args.log_file,
        console_level="DEBUG" if args.verbose else "WARNING" if not args.quiet else "ERROR",
    )

    missing = config.validate_for_llm()
    if missing:
        print(
            f"warning: {', '.join(missing)} not set -- running without an LLM "
            "(deterministic findings only; no narratives or deep investigation).",
            file=sys.stderr,
        )

    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    unknown = set(formats) - set(FORMATS)
    if unknown:
        print(
            f"error: unknown format(s) {sorted(unknown)}; choose from {', '.join(FORMATS)}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"  · {message}", file=sys.stderr)

    try:
        report = AnalysisService(config).analyze(args.repo_url, args.description, progress=progress)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(json.dumps(report, indent=2))
    elif not args.quiet:
        print_summary(report, top=args.top)

    if formats:
        paths = save_report(report, Path(args.output_dir), formats)
        print("Reports written: " + ", ".join(str(p) for p in paths), file=sys.stderr)

    if args.fail_under is not None and report.get("overall_score", 0) < args.fail_under:
        print(
            f"Score {report.get('overall_score')} is below --fail-under {args.fail_under}",
            file=sys.stderr,
        )
        return EXIT_FAIL_UNDER
    return EXIT_OK


def cmd_ui(args: argparse.Namespace) -> int:
    app_path = Path(__file__).parent / "interfaces" / "streamlit_app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        f"--server.port={args.port}",
        f"--server.address={args.host}",
    ]
    if args.headless:
        cmd.append("--server.headless=true")
    cmd += ["--browser.gatherUsageStats=false", *args.streamlit_args]
    return subprocess.call(cmd)


def cmd_mcp(args: argparse.Namespace) -> int:
    config = _load_config(args.env_file)
    # stdio transport owns stdout for the protocol: logs must go to stderr/file only.
    configure_logging(config.log_level, log_file=args.log_file)
    from drrepo.interfaces.mcp_server import run

    run(transport=args.transport, host=args.host, port=args.port)
    return EXIT_OK


def cmd_health(args: argparse.Namespace) -> int:
    from drrepo.interfaces.health_checks import check_all

    status = check_all(_load_config(args.env_file))
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(f"DrRepo {status['version']} — overall: {status['status'].upper()}")
        for name, c in status["components"].items():
            latency = f" {c['latency_ms']}ms" if c.get("latency_ms") is not None else ""
            detail = f" — {c['detail']}" if c.get("detail") else ""
            print(f"  {name:<16} {c['status']:<15}{latency}{detail}")
    return EXIT_OK if status["status"] != "unhealthy" else EXIT_ERROR


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True

    def line(passed: bool | None, label: str, detail: str = "") -> None:
        nonlocal ok
        tag = {True: " OK ", False: "FAIL", None: "WARN"}[passed]
        ok = ok and passed is not False
        print(f"[{tag}] {label}" + (f": {detail}" if detail else ""))

    print(f"DrRepo {__version__} doctor\n")
    line(sys.version_info >= (3, 11), "Python", sys.version.split()[0])
    line(
        shutil.which("git") is not None,
        "git",
        shutil.which("git") or "not on PATH (required for cloning)",
    )
    from drrepo.collectors.scanners import find_executable

    for tool in ("ruff", "bandit", "semgrep"):
        path = find_executable(tool)
        line(True if path else None, tool, path or "not found (that signal will be skipped)")

    for module in (
        "langgraph",
        "langchain",
        "langchain_groq",
        "github",
        "httpx",
        "streamlit",
        "fastapi",
        "mcp",
    ):
        try:
            importlib.import_module(module)
            line(True, f"import {module}")
        except ImportError as e:
            line(False, f"import {module}", str(e))

    try:
        config = _load_config(args.env_file)
        missing = config.validate_for_llm()
        line(
            None if missing else True,
            "configuration",
            f"missing {missing}" if missing else f"{config.model_provider}/{config.model_name}",
        )
        line(
            True if config.github_token else None,
            "GH_TOKEN",
            "set" if config.github_token else "not set (60 GitHub API requests/hour)",
        )
    except ConfigurationError as e:
        line(False, "configuration", str(e))
        config = None

    for directory in ("reports", "logs"):
        dir_path = Path(directory)
        try:
            dir_path.mkdir(exist_ok=True)
            line(os.access(dir_path, os.W_OK), f"{directory}/ writable")
        except OSError as e:
            line(False, f"{directory}/ writable", str(e))

    if config is not None and not args.offline:
        from drrepo.interfaces.health_checks import check_all

        for name, c in check_all(config)["components"].items():
            passed = {"up": True, "degraded": None, "not_configured": None}.get(c["status"], False)
            line(passed, f"connectivity: {name}", c.get("detail") or c["status"])

    print("\nAll checks passed." if ok else "\nSome checks failed -- see docs/troubleshooting.md.")
    return EXIT_OK if ok else EXIT_ERROR


def cmd_health_api(args: argparse.Namespace) -> int:
    import uvicorn

    configure_logging(_load_config(args.env_file).log_level, log_file=args.log_file)
    uvicorn.run(
        "drrepo.interfaces.health_api:app", host=args.host, port=args.port, log_level="info"
    )
    return EXIT_OK


# ---------------------------------------------------------------- parser ---


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drrepo", description="Agentic health check for public GitHub repositories."
    )
    parser.add_argument("--version", action="version", version=f"drrepo {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", default=".env", help="dotenv file to load (default: .env)")
    common.add_argument("--log-file", default="logs/app.log", help="log file path ('' to disable)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", parents=[common], help="analyze a repository")
    p.add_argument("repo_url", help="https://github.com/<owner>/<repo>")
    p.add_argument("-d", "--description", default="", help="context/focus for the investigators")
    p.add_argument(
        "--shallow", action="store_true", help="skip deep investigations (fast, deterministic)"
    )
    p.add_argument(
        "--format",
        default="json,md,sarif",
        help=f"comma-separated report formats ({', '.join(FORMATS)}); '' for none",
    )
    p.add_argument(
        "-o", "--output-dir", default="reports", help="where to write reports (default: reports/)"
    )
    p.add_argument("--json", action="store_true", help="print the full JSON report to stdout")
    p.add_argument("--top", type=int, default=10, help="issues to list in the summary")
    p.add_argument(
        "--fail-under", type=float, help="exit 3 if the overall score is below this (for CI)"
    )
    p.add_argument(
        "--no-history", action="store_true", help="don't record or compare score history"
    )
    p.add_argument("-q", "--quiet", action="store_true", help="no progress or summary output")
    p.add_argument("-v", "--verbose", action="store_true", help="print debug logs to stderr")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("ui", help="launch the Streamlit web UI")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--host", default="localhost")
    p.add_argument("--headless", action="store_true", help="don't open a browser")
    p.add_argument(
        "streamlit_args", nargs=argparse.REMAINDER, help="extra args passed to streamlit"
    )
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("mcp", parents=[common], help="run the MCP server")
    p.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("health", parents=[common], help="check external connectivity")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("doctor", parents=[common], help="diagnose the local installation")
    p.add_argument("--offline", action="store_true", help="skip network checks")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("health-api", parents=[common], help="serve the FastAPI health endpoint")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_health_api)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "analyze")  # `drrepo <url>` shorthand
    args = build_parser().parse_args(argv)
    if getattr(args, "log_file", None) == "":
        args.log_file = None
    try:
        return int(args.func(args))
    except ConfigurationError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return 130
    except Exception as e:
        logger.exception("Unexpected error")
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
