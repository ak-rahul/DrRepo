"""Check individual DrRepo v2 components: collectors, tools, and the workflow graph."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config  # noqa: E402


def check_external_tools():
    """Check whether the CLI tools collectors depend on are on PATH."""
    import shutil

    print("Checking external tools...")
    for tool in ("git", "ruff", "semgrep", "bandit"):
        path = shutil.which(tool)
        print(f"{'OK  ' if path else 'MISS'} {tool}: {path or 'not found on PATH'}")


def check_collectors():
    """Check that collector modules import and their pure functions run."""
    print("\nChecking Collectors...")

    try:
        from src.collectors.readme import analyze_readme

        result = analyze_readme("# Test\n\nSome content")
        print(f"OK   readme collector (quality_score={result.data['quality_score']})")
    except Exception as e:
        print(f"FAIL readme collector: {e}")

    for name, module, func in [
        ("github_metadata", "src.collectors.github_metadata", "collect_github_metadata"),
        ("static_analysis", "src.collectors.static_analysis", "collect_static_analysis"),
        ("security", "src.collectors.security", "collect_security"),
        ("dependency_audit", "src.collectors.dependency_audit", "collect_dependency_audit"),
        ("repo_clone", "src.collectors.repo_clone", "clone_repo"),
    ]:
        try:
            exec(f"from {module} import {func}")
            print(f"OK   {name} imports")
        except Exception as e:
            print(f"FAIL {name}: {e}")


def check_workflow(config: Config):
    """Check that the LangGraph workflow compiles."""
    print("\nChecking Workflow...")
    try:
        from src.graph.workflow import Workflow

        workflow = Workflow(config)
        print("OK   Workflow graph compiled")
    except Exception as e:
        print(f"FAIL Workflow: {e}")


def main():
    print("DrRepo v2 Component Checker\n")

    config = Config.from_env()
    check_external_tools()
    check_collectors()
    check_workflow(config)

    print("\nComponent check complete!")


if __name__ == "__main__":
    main()
