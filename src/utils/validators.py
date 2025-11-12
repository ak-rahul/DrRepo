"""Input validation utilities."""
import re
from typing import Optional

class ValidationError(Exception):
    """Custom validation error."""
    pass

def validate_github_url(url: str) -> tuple[str, str]:
    """
    Validate GitHub URL and extract owner and repo name.
    
    Args:
        url: GitHub repository URL
        
    Returns:
        Tuple of (owner, repo_name)
        
    Raises:
        ValidationError: If URL is invalid
    """
    pattern = r'github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
    match = re.search(pattern, url)
    
    if not match:
        raise ValidationError(
            f"Invalid GitHub URL: {url}. "
            "Expected format: https://github.com/owner/repo"
        )
    
    owner, repo = match.groups()
    return owner, repo

def validate_description(description: Optional[str]) -> str:
    """Validate and clean user description."""
    if not description:
        return ""
    
    # Clean and limit length
    cleaned = description.strip()
    if len(cleaned) > 500:
        cleaned = cleaned[:500] + "..."
    
    return cleaned
