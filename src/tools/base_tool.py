"""Base class for all tools."""
from abc import ABC, abstractmethod
from typing import Any, Dict
from src.utils.logger import logger

class BaseTool(ABC):
    """Abstract base class for tools."""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logger
    
    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """Execute the tool's main functionality."""
        pass
    
    def _handle_error(self, error: Exception) -> Dict:
        """Standard error handling."""
        self.logger.error(f"Error in {self.name}: {str(error)}")
        return {
            "error": str(error),
            "tool": self.name
        }
