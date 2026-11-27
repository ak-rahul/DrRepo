"""LangGraph state for one analysis run.

Parallel collector nodes each write one key into `collector_results`; parallel
category nodes each write one key into `category_findings`. Both need a merge
reducer, because LangGraph requires one whenever more than one branch in the
same superstep writes the same state key.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from drrepo.models import InvestigationPlan


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge reducer for concurrent partial updates."""
    return {**left, **right}


class State(TypedDict):
    repo_url: str
    description: str
    # Local path of the shallow clone, or None if cloning failed/was skipped.
    clone_path: str | None
    # collector name -> CollectorResult.to_dict()
    collector_results: Annotated[dict[str, Any], merge_dicts]
    # Written once by the planner node, before category nodes read it.
    investigation_plan: InvestigationPlan
    # category value -> CategoryFinding.to_dict()
    category_findings: Annotated[dict[str, Any], merge_dicts]
    # Report.to_dict(), written by the synthesizer.
    report: dict[str, Any]
