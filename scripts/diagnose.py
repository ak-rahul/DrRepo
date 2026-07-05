"""Diagnostic script for DrRepo troubleshooting (recon collectors + agentic layer)."""

import os
import shutil
import sys
from importlib import import_module

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def check_python_version():
    print_header("Python Version")
    version = sys.version_info
    print(f"Python {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("FAIL: Python 3.11+ required")
        return False
    print("PASS: Python version OK")
    return True


def check_dependencies():
    print_header("Dependencies")

    required = [
        "streamlit",
        "langchain",
        "langchain_groq",
        "langgraph",
        "github",
        "httpx",
        "fastapi",
    ]

    all_installed = True
    for package in required:
        try:
            import_module(package)
            print(f"OK   {package}")
        except ImportError:
            print(f"MISS {package} - NOT INSTALLED")
            all_installed = False
    return all_installed


def check_external_tools():
    print_header("External Tools (used by collectors)")

    all_ok = True
    for tool, required in [("git", True), ("ruff", False), ("semgrep", False), ("bandit", False)]:
        path = shutil.which(tool)
        if path:
            print(f"OK   {tool}: {path}")
        elif required:
            print(f"FAIL {tool}: not found (required for cloning repositories)")
            all_ok = False
        else:
            print(f"SKIP {tool}: not found (that collector will be skipped, not fatal)")
    return all_ok


def check_environment():
    print_header("Environment Configuration")

    from src.config import Config

    config = Config.from_env()
    missing = config.validate_for_llm()

    print(f"MODEL_PROVIDER: {config.model_provider}")
    print(f"GROQ_API_KEY: {'set' if config.groq_api_key else 'NOT SET'}")
    print(f"OPENAI_API_KEY: {'set' if config.openai_api_key else 'NOT SET'}")
    print(f"GH_TOKEN: {'set' if config.github_token else 'not set (optional, raises rate limits)'}")

    if missing:
        print(f"\nFAIL: Missing required keys for {config.model_provider}: {missing}")
        return False
    print("\nPASS: LLM configuration OK")
    return True


def check_imports():
    print_header("DrRepo Modules")

    modules = [
        "src.config",
        "src.models",
        "src.utils.logger",
        "src.utils.health_check",
        "src.utils.exceptions",
        "src.collectors.github_metadata",
        "src.collectors.readme",
        "src.agents.planner",
        "src.agents.investigator",
        "src.tools.file_tools",
        "src.graph.workflow",
        "src.main",
    ]

    all_imported = True
    for module in modules:
        try:
            import_module(module)
            print(f"OK   {module}")
        except Exception as e:
            print(f"FAIL {module} - {str(e)[:60]}")
            all_imported = False
    return all_imported


def check_api_connectivity():
    print_header("API Connectivity")

    from src.config import Config

    config = Config.from_env()

    github_ok = False
    try:
        from github import Auth, Github

        auth = Auth.Token(config.github_token) if config.github_token else None
        gh = Github(auth=auth, timeout=5) if auth else Github(timeout=5)
        gh.get_rate_limit()
        print("OK   GitHub API: Connected (rate limit resources available)")
        github_ok = True
    except Exception as e:
        print(f"FAIL GitHub API: {str(e)[:60]}")

    groq_ok = False
    if config.model_provider == "groq":
        try:
            from langchain_groq import ChatGroq

            llm = ChatGroq(api_key=config.groq_api_key, model=config.model_name, timeout=5)
            llm.invoke("ping")
            print("OK   Groq API: Connected")
            groq_ok = True
        except Exception as e:
            print(f"FAIL Groq API: {str(e)[:60]}")
    else:
        groq_ok = True  # not applicable

    osv_ok = False
    try:
        import httpx

        httpx.get("https://api.osv.dev/v1/query", timeout=5)
        print("OK   OSV.dev connectivity: reachable")
        osv_ok = True
    except Exception as e:
        print(f"FAIL OSV.dev connectivity: {str(e)[:60]}")

    return github_ok and groq_ok and osv_ok


def check_file_permissions():
    print_header("File Permissions")

    directories = ["logs", "reports"]
    all_ok = True

    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
                print(f"OK   {directory}/: Created")
            except Exception as e:
                print(f"FAIL {directory}/: Cannot create - {e}")
                all_ok = False
        elif os.access(directory, os.W_OK):
            print(f"OK   {directory}/: Writable")
        else:
            print(f"FAIL {directory}/: NOT writable")
            all_ok = False

    return all_ok


def main():
    print("\nDrRepo Diagnostic Tool")
    print("=" * 60)

    results = {
        "python": check_python_version(),
        "dependencies": check_dependencies(),
        "external_tools": check_external_tools(),
        "environment": check_environment(),
        "imports": check_imports(),
        "api": check_api_connectivity(),
        "permissions": check_file_permissions(),
    }

    print_header("Diagnostic Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\nPassed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")

    if all(results.values()):
        print("\nAll checks passed! DrRepo should work correctly.")
        return 0
    print("\nSome checks failed. See docs/TROUBLESHOOTING.md for help.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
