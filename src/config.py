"""Configuration for DrRepo v2.

Deliberately NOT a module-level singleton. Every collector/agent takes a
`Config` instance via constructor injection, so tests can build one with fake
values and never touch `os.environ` or real credentials. Call `Config.from_env()`
exactly once at a real entrypoint (CLI, Streamlit app, health API).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration. Build via `Config.from_env()` or directly for tests."""

    # API keys
    groq_api_key: str = ""
    openai_api_key: str = ""
    github_token: str = ""

    # Model configuration
    model_provider: str = "groq"
    model_name: str = "llama-3.3-70b-versatile"
    temperature: float = 0.3
    max_tokens: int = 2000

    # Application settings
    log_level: str = "INFO"

    # Retry configuration
    retry_backoff_factor: float = 2.0
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 60.0

    # Clone/collector limits
    clone_timeout_seconds: int = 60
    clone_max_size_mb: int = 300
    collector_timeout_seconds: int = 120

    # Feature toggles (let a deployment disable a heavy/optional collector)
    enable_semgrep: bool = True
    enable_bandit: bool = True
    enable_dependency_audit: bool = True
    enable_license_audit: bool = True

    # Agentic investigation (v3): bounds on the tool-calling investigator loops
    max_tool_calls_per_investigator: int = 8
    investigator_timeout_seconds: int = 90
    # Kill switch: force every category "shallow" (v2 behavior) -- a regression
    # safety net and a cost control for anyone who wants the fast/cheap mode.
    enable_deep_investigation: bool = True

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env_file: Optional[str] = ".env") -> "Config":
        """Load configuration from environment variables (and `.env` if present).

        This is the ONE place that touches `os.environ` — call it once at a
        real entrypoint, then pass the resulting `Config` down explicitly.
        """
        import os

        from dotenv import load_dotenv

        if env_file:
            load_dotenv(env_file)

        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            github_token=os.getenv("GH_TOKEN", ""),
            model_provider=os.getenv("MODEL_PROVIDER", "groq"),
            model_name=os.getenv("MODEL_NAME", "llama-3.3-70b-versatile"),
            temperature=float(os.getenv("TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("MAX_TOKENS", "2000")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            retry_backoff_factor=float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0")),
            retry_initial_delay=float(os.getenv("RETRY_INITIAL_DELAY", "1.0")),
            retry_max_delay=float(os.getenv("RETRY_MAX_DELAY", "60.0")),
            clone_timeout_seconds=int(os.getenv("CLONE_TIMEOUT_SECONDS", "60")),
            clone_max_size_mb=int(os.getenv("CLONE_MAX_SIZE_MB", "300")),
            collector_timeout_seconds=int(os.getenv("COLLECTOR_TIMEOUT_SECONDS", "120")),
            enable_semgrep=os.getenv("ENABLE_SEMGREP", "true").lower() == "true",
            enable_bandit=os.getenv("ENABLE_BANDIT", "true").lower() == "true",
            enable_dependency_audit=os.getenv("ENABLE_DEPENDENCY_AUDIT", "true").lower() == "true",
            enable_license_audit=os.getenv("ENABLE_LICENSE_AUDIT", "true").lower() == "true",
            max_tool_calls_per_investigator=int(os.getenv("MAX_TOOL_CALLS_PER_INVESTIGATOR", "8")),
            investigator_timeout_seconds=int(os.getenv("INVESTIGATOR_TIMEOUT_SECONDS", "90")),
            enable_deep_investigation=os.getenv("ENABLE_DEEP_INVESTIGATION", "true").lower()
            == "true",
        )

    def validate_for_llm(self) -> list[str]:
        """Return a list of missing required keys for the configured LLM provider.

        Empty list means valid. Callers decide what to do with a non-empty
        list (raise, warn, disable LLM-dependent agents, etc.) -- this method
        never raises itself, so it stays trivially testable.
        """
        missing = []
        if self.model_provider == "groq" and not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        elif self.model_provider == "openai" and not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        return missing
