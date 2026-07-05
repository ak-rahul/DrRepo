"""Verify all DrRepo imports work correctly (recon collectors + agentic layer)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify_imports():
    """Verify all module imports."""
    print("Verifying Imports...\n")

    imports = [
        # Config / models / utils
        ("src.config", "Config"),
        ("src.models", "Report"),
        ("src.utils.logger", "logger"),
        ("src.utils.retry", "retry_with_backoff"),
        ("src.utils.health_check", "HealthChecker"),
        ("src.utils.exceptions", "DrRepoException"),
        ("src.utils.circuit_breaker", "CircuitBreaker"),
        # Collectors
        ("src.collectors.repo_clone", "clone_repo"),
        ("src.collectors.github_metadata", "collect_github_metadata"),
        ("src.collectors.readme", "analyze_readme"),
        ("src.collectors.static_analysis", "collect_static_analysis"),
        ("src.collectors.security", "collect_security"),
        ("src.collectors.dependency_audit", "collect_dependency_audit"),
        # Agents
        ("src.agents.base", "BaseAnalystAgent"),
        ("src.agents.docs_analyst", "DocsAnalyst"),
        ("src.agents.code_quality_analyst", "CodeQualityAnalyst"),
        ("src.agents.security_analyst", "SecurityAnalyst"),
        ("src.agents.dependency_analyst", "DependencyAnalyst"),
        ("src.agents.maintainability_analyst", "MaintainabilityAnalyst"),
        ("src.agents.planner", "LeadInvestigator"),
        ("src.agents.investigator", "investigate"),
        # Tools (the agentic surface: LLM-callable, read-only, sandboxed)
        ("src.tools.file_tools", "make_file_tools"),
        ("src.tools.scan_tools", "make_scan_tools"),
        ("src.tools.dependency_tools", "make_dependency_tools"),
        ("src.tools.git_tools", "make_git_history_tools"),
        # Graph / report / main
        ("src.graph.state", "State"),
        ("src.graph.workflow", "Workflow"),
        ("src.report.synthesizer", "synthesize_report"),
        ("src.report.exporters", "to_json"),
        ("src.main", "main"),
    ]

    failed = []
    for module, name in imports:
        try:
            exec(f"from {module} import {name}")
            print(f"OK   {module}.{name}")
        except Exception as e:
            print(f"FAIL {module}.{name}: {str(e)[:80]}")
            failed.append((module, name, str(e)))

    if failed:
        print(f"\n{len(failed)} import(s) failed:")
        for module, name, error in failed:
            print(f"   - {module}.{name}: {error[:80]}")
        return 1

    print(f"\nAll {len(imports)} imports successful!")
    return 0


if __name__ == "__main__":
    sys.exit(verify_imports())
