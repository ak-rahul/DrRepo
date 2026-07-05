"""Workflow state for the DrRepo v2 pipeline.

Collectors fan out in parallel and each writes into `collector_results` under
its own key; analyst agents fan out in parallel and each writes into
`category_findings` under its own key. Both need a merge reducer since
LangGraph requires one whenever more than one parallel branch can write to the
same state key.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from src.models import InvestigationPlan


def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-merge reducer for concurrent partial state updates."""
    merged = dict(left)
    merged.update(right)
    return merged


class State(TypedDict):
    """State schema for the repository analysis workflow.

    Every key the pipeline actually reads or writes is declared here -- v1's
    `State` silently omitted `final_summary` even though the workflow used it
    throughout; this schema is meant to stay in sync with real usage.
    """

    # Input
    repo_url: str
    description: str

    # Local filesystem path of the shallow clone, if cloning succeeded.
    # Absent (not just None) when there is no clone -- collectors check with
    # `state.get("clone_path")`.
    clone_path: Optional[str]

    # Populated by parallel collector nodes (each collector writes one key,
    # e.g. "github_metadata", "readme", "static_analysis", "security",
    # "dependency_audit"). Value shape: CollectorResult-as-dict.
    collector_results: Annotated[Dict[str, Any], merge_dicts]

    # Populated by the planner node once, after all collectors finish. Each
    # category node reads this to decide shallow vs. deep. No reducer needed
    # -- only the planner node ever writes it, before the parallel category
    # nodes that read it run.
    investigation_plan: InvestigationPlan

    # Populated by parallel analyst agent nodes, one key per Category value.
    # Value shape: {"summary": str, "score": float, "issues": [Issue-as-dict]}
    category_findings: Annotated[Dict[str, Any], merge_dicts]

    # Populated by the synthesizer node. Report.to_dict() shape.
    report: Dict[str, Any]

    # Bookkeeping
    errors: Annotated[List[str], add]
