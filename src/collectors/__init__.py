"""Deterministic, non-LLM collectors.

Each collector is a plain function returning a `CollectorResult`. Import
directly from the submodule you need (e.g. `from src.collectors.readme import
analyze_readme`) rather than from this package -- keeping this file empty
means importing one collector never pulls in another collector's dependencies
(e.g. testing the README analyzer never requires PyGithub or httpx).
"""
