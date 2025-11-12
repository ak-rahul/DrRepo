"""Configuration management for Publication Assistant."""
import os
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    """Application configuration."""
    
    # API Keys
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    
    # Model Configuration
    model_name: str = os.getenv("MODEL_NAME", "gpt-4")
    temperature: float = float(os.getenv("TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("MAX_TOKENS", "2000"))
    
    # Application Settings
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    timeout: int = int(os.getenv("TIMEOUT", "30"))
    
    # LangSmith (optional for observability)
    langsmith_api_key: Optional[str] = os.getenv("LANGCHAIN_API_KEY")
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "publication-assistant")
    langsmith_tracing: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    
    def validate(self) -> bool:
        """Validate required configuration."""
        required_keys = [
            self.openai_api_key,
            self.github_token,
            self.tavily_api_key
        ]
        return all(required_keys)

# Global config instance
config = Config()
