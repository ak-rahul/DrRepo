"""State management for the publication assistant workflow."""
from typing import TypedDict, Dict, List, Optional, Annotated
import operator
from langgraph.graph import add_messages

class PublicationState(TypedDict):
    """
    Shared state for the multi-agent publication assistant workflow.
    
    Uses reducer functions for safe concurrent updates.
    """
    
    # Input
    repo_url: str
    user_description: str
    
    # Repository data
    repo_data: Dict
    readme_content: str
    code_structure: Dict
    
    # Agent outputs (using append reducer for lists)
    metadata_suggestions: Annotated[List[Dict], operator.add]
    content_improvements: Annotated[List[Dict], operator.add]
    review_feedback: Annotated[List[Dict], operator.add]
    fact_check_results: Annotated[List[Dict], operator.add]
    
    # Final consolidated output
    final_recommendations: Dict
    
    # Agent communication messages
    messages: Annotated[list, add_messages]
    
    # Workflow metadata
    current_agent: str
    workflow_status: str
    errors: Annotated[List[str], operator.add]

def create_initial_state(repo_url: str, user_description: str = "") -> PublicationState:
    """Create initial state for workflow."""
    return PublicationState(
        repo_url=repo_url,
        user_description=user_description,
        repo_data={},
        readme_content="",
        code_structure={},
        metadata_suggestions=[],
        content_improvements=[],
        review_feedback=[],
        fact_check_results=[],
        final_recommendations={},
        messages=[],
        current_agent="initializer",
        workflow_status="started",
        errors=[]
    )
