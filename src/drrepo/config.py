"""Configuration for DrRepo.

Deliberately NOT a module-level singleton. Every collector/agent takes a
`Config` instance via constructor injection, so tests can build one with fake
values and never touch `os.environ` or real credentials. Call `Config.from_env()`
exactly once at a real entrypoint (CLI, Streamlit app, health API).

`Config` is frozen (one instance is shared by concurrent runs) and validated on
construction, however it is built. Derive per-run variants with
`dataclasses.replace(config, ...)`, which validates again.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

from drrepo.errors import ConfigurationError

SUPPORTED_PROVIDERS = ("groq", "openai", "anthropic", "ollama")
# Used when MODEL_NAME is unset. Override any of them with MODEL_NAME / MODEL_NAME_<ROLE>.
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5-5",
    "ollama": "llama3.1",
}
# Roles a model can be chosen for. "planner" also serves the documentation rubric
# (both are structured-output calls); "narrative" writes summaries; "investigation"
# runs the tool-calling deep investigations.
LLM_ROLES = ("planner", "narrative", "investigation", "critic")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

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


def _env_list(name: str) -> tuple[str, ...]:
    """Comma-separated values, stripped; empty entries dropped."""
    return tuple(v.strip() for v in os.getenv(name, "").split(",") if v.strip())


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as e:
        raise ConfigurationError(f"{name}={raw!r} is not a number") from e


@dataclass(frozen=True)
class Config:
    """Application configuration. Build via `Config.from_env()` or directly for tests."""

    # API keys
    groq_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    github_token: str = ""

    # Model configuration. Empty model names fall back: role -> MODEL_NAME -> provider default.
    model_provider: str = "groq"
    model_name: str = ""
    model_name_planner: str = ""
    model_name_narrative: str = ""
    model_name_investigation: str = ""
    model_name_critic: str = ""
    ollama_base_url: str = "http://localhost:11434"
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
    # License policy (SPDX ids, case-insensitive). When either is set it replaces the
    # built-in copyleft heuristic: deny-listed licenses are violations, and with an
    # allow-list every other known license is too.
    license_deny: tuple[str, ...] = ()
    license_allow: tuple[str, ...] = ()
    enable_workflow_audit: bool = True  # zizmor over .github/workflows
    enable_dockerfile_audit: bool = True  # hadolint + root-user check over Dockerfiles
    enable_scorecard: bool = True  # OpenSSF Scorecard checks a shallow clone can't see

    # Agentic investigation: bounds on the tool-calling investigator loops.
    max_tool_calls_per_investigator: int = 8
    investigator_timeout_seconds: int = 90
    # Kill switch: force every category "shallow" -- a regression safety net
    # and a cost control for anyone who wants the fast/cheap mode.
    enable_deep_investigation: bool = True
    # Bounded LLM judgment that can adjust a score (today: the documentation rubric).
    enable_llm_judgment: bool = True
    # Second look at high/critical agent findings (agents/critic.py). It can lower
    # or dispute a severity, never raise one or remove a finding.
    enable_agent_critic: bool = True
    # Investigators call their tools through DrRepo's own MCP tool server
    # (agents/tool_server.py, in memory). False = call the same tools in-process.
    enable_mcp_tools: bool = True

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

    # Per-package OSV/deps.dev lookup cache (shared across runs in one
    # process, such as the Streamlit app -- see service.py).
    enable_dependency_lookup_cache: bool = True

    # Suppressions (report/suppressions.py). A file you pass always applies; the
    # analyzed repository's own .drrepo.toml only when explicitly trusted.
    suppressions_file: str = ""
    trust_repo_suppressions: bool = False

    # Score history: append each run's scores to reports/history.json so a
    # later run can report a delta against the previous analysis.
    enable_score_history: bool = True

    def __post_init__(self) -> None:
        """Reject values that would only fail later, deep inside a run.

        Raises:
            ConfigurationError: naming the offending setting by its env var.
        """
        problems: list[str] = []
        if self.model_provider not in SUPPORTED_PROVIDERS:
            problems.append(
                f"MODEL_PROVIDER={self.model_provider!r} is not supported "
                f"(choose one of: {', '.join(SUPPORTED_PROVIDERS)})"
            )
        if self.log_level not in LOG_LEVELS:
            problems.append(f"LOG_LEVEL={self.log_level!r} is not one of {', '.join(LOG_LEVELS)}")
        if not 0.0 <= self.temperature <= 2.0:
            problems.append(f"TEMPERATURE={self.temperature} must be between 0 and 2")
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in _MUST_BE_POSITIVE and value < 1:
                problems.append(f"{f.name.upper()}={value} must be at least 1")
            elif f.name in _MUST_BE_NON_NEGATIVE and value < 0:
                problems.append(f"{f.name.upper()}={value} must not be negative")
        if problems:
            raise ConfigurationError("; ".join(problems))

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> Config:
        """Load configuration from environment variables (and `env_file` if present).

        This is the ONE place that touches `os.environ` -- call it once at a
        real entrypoint, then pass the resulting `Config` down explicitly.

        Raises:
            ConfigurationError: a variable is set but can't be parsed, or its
                value is out of range (see `__post_init__`).
        """
        from dotenv import load_dotenv

        if env_file:
            # `.env.local` (machine-specific secrets, never committed) wins over `.env`;
            # real environment variables win over both (load_dotenv never overrides).
            local = Path(env_file).with_name(Path(env_file).name + ".local")
            if local.is_file():
                load_dotenv(local)
            load_dotenv(env_file)

        d = cls()  # defaults, so each default lives in exactly one place
        config = cls(
            groq_api_key=_env_str("GROQ_API_KEY", ""),
            openai_api_key=_env_str("OPENAI_API_KEY", ""),
            anthropic_api_key=_env_str("ANTHROPIC_API_KEY", ""),
            github_token=_env_str("GH_TOKEN", "") or _env_str("GITHUB_TOKEN", ""),
            model_provider=_env_str("MODEL_PROVIDER", d.model_provider).lower(),
            model_name=_env_str("MODEL_NAME", d.model_name),
            model_name_planner=_env_str("MODEL_NAME_PLANNER", d.model_name_planner),
            model_name_narrative=_env_str("MODEL_NAME_NARRATIVE", d.model_name_narrative),
            model_name_investigation=_env_str(
                "MODEL_NAME_INVESTIGATION", d.model_name_investigation
            ),
            model_name_critic=_env_str("MODEL_NAME_CRITIC", d.model_name_critic),
            ollama_base_url=_env_str("OLLAMA_BASE_URL", d.ollama_base_url),
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
            license_deny=_env_list("LICENSE_DENY"),
            license_allow=_env_list("LICENSE_ALLOW"),
            enable_workflow_audit=_env_bool("ENABLE_WORKFLOW_AUDIT", d.enable_workflow_audit),
            enable_dockerfile_audit=_env_bool("ENABLE_DOCKERFILE_AUDIT", d.enable_dockerfile_audit),
            enable_scorecard=_env_bool("ENABLE_SCORECARD", d.enable_scorecard),
            max_tool_calls_per_investigator=_env_int(
                "MAX_TOOL_CALLS_PER_INVESTIGATOR", d.max_tool_calls_per_investigator
            ),
            investigator_timeout_seconds=_env_int(
                "INVESTIGATOR_TIMEOUT_SECONDS", d.investigator_timeout_seconds
            ),
            enable_deep_investigation=_env_bool(
                "ENABLE_DEEP_INVESTIGATION", d.enable_deep_investigation
            ),
            enable_llm_judgment=_env_bool("ENABLE_LLM_JUDGMENT", d.enable_llm_judgment),
            enable_agent_critic=_env_bool("ENABLE_AGENT_CRITIC", d.enable_agent_critic),
            enable_mcp_tools=_env_bool("ENABLE_MCP_TOOLS", d.enable_mcp_tools),
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
            suppressions_file=_env_str("SUPPRESSIONS_FILE", d.suppressions_file),
            trust_repo_suppressions=_env_bool("TRUST_REPO_SUPPRESSIONS", d.trust_repo_suppressions),
        )
        return config

    def model_for(self, role: str | None = None) -> str:
        """The model for `role` (one of LLM_ROLES), else MODEL_NAME, else the provider default."""
        by_role = {
            "planner": self.model_name_planner,
            "narrative": self.model_name_narrative,
            "investigation": self.model_name_investigation,
            "critic": self.model_name_critic,
        }
        return by_role.get(role or "") or self.model_name or DEFAULT_MODELS[self.model_provider]

    def models_by_role(self) -> dict[str, str]:
        return {role: self.model_for(role) for role in LLM_ROLES}

    def api_key(self) -> str:
        """The API key for the configured provider ("" for keyless providers like Ollama)."""
        return {
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(self.model_provider, "")

    def validate_for_llm(self) -> list[str]:
        """Return the missing required keys for the configured LLM provider.

        Empty list means valid (Ollama needs no key). Never raises, so callers decide.
        """
        if self.model_provider == "ollama":
            return []
        if not self.api_key():
            return [f"{self.model_provider.upper()}_API_KEY"]
        return []


# Field names double as env var names (upper-cased) in validation messages.
_MUST_BE_POSITIVE = frozenset(
    {
        "max_tokens",
        "llm_request_timeout_seconds",
        "clone_timeout_seconds",
        "clone_max_size_mb",
        "collector_timeout_seconds",
        "max_tool_calls_per_investigator",
        "investigator_timeout_seconds",
        "llm_circuit_breaker_threshold",
        "estimated_tokens_per_deep_investigation",
    }
)
_MUST_BE_NON_NEGATIVE = frozenset(
    {"llm_circuit_breaker_timeout_seconds", "llm_token_budget_per_run"}
)
