"""Custom exceptions for DrRepo."""


class DrRepoException(Exception):
    """Base exception for DrRepo.
    
    All custom exceptions inherit from this class for easy catching
    and identification of DrRepo-specific errors.
    """
    pass


class APIConnectionError(DrRepoException):
    """Raised when external API connection fails.
    
    Examples:
        - Network timeout
        - Connection refused
        - DNS resolution failure
    """
    pass


class ConfigurationError(DrRepoException):
    """Raised when configuration is invalid.
    
    Examples:
        - Missing API keys
        - Invalid configuration values
        - Environment variable errors
    """
    pass


class RepositoryNotFoundError(DrRepoException):
    """Raised when GitHub repository doesn't exist.
    
    This is a 404 error from GitHub API indicating the repository
    either doesn't exist or the user doesn't have access to it.
    """
    pass


class RateLimitError(DrRepoException):
    """Raised when API rate limit is exceeded.
    
    Examples:
        - GitHub API rate limit (5000/hour for authenticated)
        - Groq API rate limit
        - Tavily API rate limit
    """
    
    def __init__(self, message: str, retry_after: int = None):
        """Initialize rate limit error.
        
        Args:
            message: Error message
            retry_after: Seconds until rate limit resets (optional)
        """
        super().__init__(message)
        self.retry_after = retry_after


class AnalysisError(DrRepoException):
    """Raised when analysis fails.
    
    Examples:
        - Agent execution failure
        - LLM response parsing error
        - Workflow state corruption
    """
    pass


class ValidationError(DrRepoException):
    """Raised when input validation fails.
    
    Examples:
        - Invalid repository URL
        - Malformed input data
        - Schema validation failure
    """
    pass


class ToolExecutionError(DrRepoException):
    """Raised when a tool execution fails.
    
    Examples:
        - GitHubTool failure
        - WebSearchTool failure
        - RAGRetriever failure
    """
    
    def __init__(self, tool_name: str, message: str, original_error: Exception = None):
        """Initialize tool execution error.
        
        Args:
            tool_name: Name of the tool that failed
            message: Error message
            original_error: Original exception that caused the failure
        """
        super().__init__(f"{tool_name}: {message}")
        self.tool_name = tool_name
        self.original_error = original_error


class AgentExecutionError(DrRepoException):
    """Raised when an agent execution fails.
    
    Examples:
        - RepoAnalyzer failure
        - LLM timeout
        - Invalid agent state
    """
    
    def __init__(self, agent_name: str, message: str, original_error: Exception = None):
        """Initialize agent execution error.
        
        Args:
            agent_name: Name of the agent that failed
            message: Error message
            original_error: Original exception that caused the failure
        """
        super().__init__(f"{agent_name}: {message}")
        self.agent_name = agent_name
        self.original_error = original_error
