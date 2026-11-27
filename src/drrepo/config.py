"""Configuration for DrRepo.

Deliberately NOT a module-level singleton. Every collector/agent takes a
`Config` instance via constructor injection, so tests can build one with fake
values and never touch `os.environ` or real credentials. Call `Config.from_env()`
exactly once at a real entrypoint (CLI, Streamlit app, health API).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from drrepo.core.errors import ConfigurationError

SUPPORTED_PROVIDERS = ("groq", "openai")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigurationError(f"{name}={raw!r} is not a boolean (use true/false)")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as e:
        raise ConfigurationError(f"{name}={raw!r} is not an integer") from e


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as e:
        raise ConfigurationError(f"{name}={raw!r} is not a number") from e


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
    llm_request_timeout_seconds: int = 60

    # Application settings
    log_level: str = "INFO"

    # Clone/collector limits
    clone_timeout_seconds: int = 60
    clone_max_size_mb: int = 300
    collector_timeout_seconds: int = 120

    # Feature toggles (let a deployment disable a heavy/optional collector)
    enable_semgrep: bool = True
    enable_bandit: bool = True
    enable_dependency_audit: bool = True
    enable_license_audit: bool = True

    # Agentic investigation: bounds on the tool-calling investigator loops.
    max_tool_calls_per_investigator: int = 8
    investigator_timeout_seconds: int = 90
    # Kill switch: force every category "shallow" -- a regression safety net
    # and a cost control for anyone who wants the fast/cheap mode.
    enable_deep_investigation: bool = True

    # LLM circuit breaker: opens after repeated LLM-call failures so parallel
    # category nodes fail fast instead of each retrying an exhausted quota.
    enable_llm_circuit_breaker: bool = True
    llm_circuit_breaker_threshold: int = 3
    llm_circuit_breaker_timeout_seconds: int = 300

    # LLM token budget: a rough, per-run cap so the planner's shallow/deep
    # decisions are cost-aware. A "deep" category falls back to shallow if
    # the run can't afford another investigation.
    enable_llm_budget_tracking: bool = True
    llm_token_budget_per_run: int = 60000
    estimated_tokens_per_deep_investigation: int = 12000

    # Per-package OSV/deps.dev lookup cache (shared across runs in the
    # Streamlit app and MCP server -- see service.py).
    enable_dependency_lookup_cache: bool = True

    # Score history: append each run's scores to reports/history.json so a
    # later run can report a delta against the previous analysis.
    enable_score_history: bool = True

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> Config:
        """Load configuration from environment variables (and `env_file` if present).

        This is the ONE place that touches `os.environ` -- call it once at a
        real entrypoint, then pass the resulting `Config` down explicitly.

        Raises:
            ConfigurationError: a variable is set but can't be parsed, or
                `MODEL_PROVIDER` names an unsupported provider.
        """
        from dotenv import load_dotenv

        if env_file:
            load_dotenv(env_file)

        d = cls()  # defaults, so each default lives in exactly one place
        config = cls(
            groq_api_key=_env_str("GROQ_API_KEY", ""),
            openai_api_key=_env_str("OPENAI_API_KEY", ""),
            github_token=_env_str("GH_TOKEN", "") or _env_str("GITHUB_TOKEN", ""),
            model_provider=_env_str("MODEL_PROVIDER", d.model_provider).lower(),
            model_name=_env_str("MODEL_NAME", d.model_name),
            temperature=_env_float("TEMPERATURE", d.temperature),
            max_tokens=_env_int("MAX_TOKENS", d.max_tokens),
            llm_request_timeout_seconds=_env_int(
                "LLM_REQUEST_TIMEOUT_SECONDS", d.llm_request_timeout_seconds
            ),
            log_level=_env_str("LOG_LEVEL", d.log_level).upper(),
            clone_timeout_seconds=_env_int("CLONE_TIMEOUT_SECONDS", d.clone_timeout_seconds),
            clone_max_size_mb=_env_int("CLONE_MAX_SIZE_MB", d.clone_max_size_mb),
            collector_timeout_seconds=_env_int(
                "COLLECTOR_TIMEOUT_SECONDS", d.collector_timeout_seconds
            ),
            enable_semgrep=_env_bool("ENABLE_SEMGREP", d.enable_semgrep),
            enable_bandit=_env_bool("ENABLE_BANDIT", d.enable_bandit),
            enable_dependency_audit=_env_bool("ENABLE_DEPENDENCY_AUDIT", d.enable_dependency_audit),
            enable_license_audit=_env_bool("ENABLE_LICENSE_AUDIT", d.enable_license_audit),
            max_tool_calls_per_investigator=_env_int(
                "MAX_TOOL_CALLS_PER_INVESTIGATOR", d.max_tool_calls_per_investigator
            ),
            investigator_timeout_seconds=_env_int(
                "INVESTIGATOR_TIMEOUT_SECONDS", d.investigator_timeout_seconds
            ),
            enable_deep_investigation=_env_bool(
                "ENABLE_DEEP_INVESTIGATION", d.enable_deep_investigation
            ),
            enable_llm_circuit_breaker=_env_bool(
                "ENABLE_LLM_CIRCUIT_BREAKER", d.enable_llm_circuit_breaker
            ),
            llm_circuit_breaker_threshold=_env_int(
                "LLM_CIRCUIT_BREAKER_THRESHOLD", d.llm_circuit_breaker_threshold
            ),
            llm_circuit_breaker_timeout_seconds=_env_int(
                "LLM_CIRCUIT_BREAKER_TIMEOUT_SECONDS", d.llm_circuit_breaker_timeout_seconds
            ),
            enable_llm_budget_tracking=_env_bool(
                "ENABLE_LLM_BUDGET_TRACKING", d.enable_llm_budget_tracking
            ),
            llm_token_budget_per_run=_env_int(
                "LLM_TOKEN_BUDGET_PER_RUN", d.llm_token_budget_per_run
            ),
            estimated_tokens_per_deep_investigation=_env_int(
                "ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION", d.estimated_tokens_per_deep_investigation
            ),
            enable_dependency_lookup_cache=_env_bool(
                "ENABLE_DEPENDENCY_LOOKUP_CACHE", d.enable_dependency_lookup_cache
            ),
            enable_score_history=_env_bool("ENABLE_SCORE_HISTORY", d.enable_score_history),
        )
        if config.model_provider not in SUPPORTED_PROVIDERS:
            raise ConfigurationError(
                f"MODEL_PROVIDER={config.model_provider!r} is not supported "
                f"(choose one of: {', '.join(SUPPORTED_PROVIDERS)})"
            )
        return config

    def validate_for_llm(self) -> list[str]:
        """Return the missing required keys for the configured LLM provider.

        Empty list means valid. Never raises, so callers decide what to do.
        """
        if self.model_provider == "groq" and not self.groq_api_key:
            return ["GROQ_API_KEY"]
        if self.model_provider == "openai" and not self.openai_api_key:
            return ["OPENAI_API_KEY"]
        return []
