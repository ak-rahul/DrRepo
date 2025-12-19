"""Configuration management for DrRepo."""

import os
from typing import Optional
from dataclasses import dataclass

from dotenv import load_dotenv

from src.utils.logger import logger

load_dotenv()


@dataclass
class Config:
    """Application configuration with retry settings."""

    # API Keys
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    github_token: str = os.getenv("GH_TOKEN", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    # Model Configuration
    model_provider: str = os.getenv("MODEL_PROVIDER", "groq")
    model_name: str = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
    temperature: float = float(os.getenv("TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("MAX_TOKENS", "2000"))

    # Application Settings
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    timeout: int = int(os.getenv("TIMEOUT", "30"))
    
    # Retry Configuration
    retry_backoff_factor: float = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
    retry_initial_delay: float = float(os.getenv("RETRY_INITIAL_DELAY", "1.0"))
    retry_max_delay: float = float(os.getenv("RETRY_MAX_DELAY", "60.0"))

    # LangSmith (optional for observability)
    langsmith_api_key: Optional[str] = os.getenv("LANGCHAIN_API_KEY")
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "drrepo")
    langsmith_tracing: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"

    def validate(self) -> bool:
        """Validate that required API keys are present.

        Returns:
            True if all required keys present, False otherwise
        """
        # Check based on provider
        if self.model_provider == 'groq':
            required = [
                ('GROQ_API_KEY', self.groq_api_key),
                ('GH_TOKEN', self.github_token),
                ('TAVILY_API_KEY', self.tavily_api_key)
            ]
        else:
            required = [
                ('OPENAI_API_KEY', self.openai_api_key),
                ('GH_TOKEN', self.github_token),
                ('TAVILY_API_KEY', self.tavily_api_key)
            ]

        missing = [key for key, value in required if not value]

        if missing:
            logger.error(f"Missing required API keys: {', '.join(missing)}")
            return False

        return True


# Global config instance
config = Config()
