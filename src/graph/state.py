"""State management for DrRepo workflow."""
from typing import TypedDict, List, Dict, Annotated
from operator import add


class State(TypedDict):
    """State schema for publication assistant workflow.
    
    Attributes:
        repo_url: GitHub repository URL
        description: Optional repository description
        repo_data: Fetched repository data
        code_structure: README analysis results
        analysis: List of agent analyses
        metadata_recommendations: Metadata improvement suggestions
        content_improvements: Content improvement suggestions
        quality_review: Quality review results
        fact_check_results: Fact checking results
        messages: Conversation messages
        current_agent: Currently executing agent
        errors: List of errors encountered
    """
    
    # Input
    repo_url: str
    description: str
    
    # Repository data
    repo_data: Dict
    code_structure: Dict
    
    # Agent outputs
    analysis: Annotated[List[Dict], add]
    metadata_recommendations: Annotated[List[Dict], add]
    content_improvements: Annotated[List[Dict], add]
    quality_review: Annotated[List[Dict], add]
    fact_check_results: Annotated[List[Dict], add]
    
    # Workflow state
    messages: Annotated[List, add]
    current_agent: str
    errors: Annotated[List[str], add]
