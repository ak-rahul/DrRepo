"""Configuration for DrRepo.

Every setting and its default lives in `defaults.toml` (next to this module),
with per-provider defaults in its `[providers.<name>]` tables. `Config.from_env()`
layers the environment on top: real environment variables, then `.env.local`,
then `.env`, then the provider's table, then the file's defaults. API keys are
not in the file; they come from the environment only.

Deliberately NOT a module-level singleton. Every collector/agent takes a
`Config` instance via constructor injection, so tests can build one with fake
values and never touch `os.environ` or real credentials. Call `Config.from_env()`
exactly once at a real entrypoint (CLI, Streamlit app, local API). `Config()`
alone gives the file's defaults without any provider table.

`Config` is frozen (one instance is shared by concurrent runs) and validated on
construction, however it is built. Derive per-run variants with
`dataclasses.replace(config, ...)`, which validates again.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from importlib import resources
from pathlib import Path
from typing import Any

from drrepo.errors import ConfigurationError

SUPPORTED_PROVIDERS = ("groq", "openai", "anthropic", "ollama")
STORE_BACKENDS = ("json", "sqlite")
# Used when MODEL_NAME is unset. Override any of them with MODEL_NAME / MODEL_NAME_<ROLE>.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5-5",
    "ollama": "llama3.1",
}
# Roles a model can be chosen for. "planner" also serves the documentation rubric
# (both are structured-output calls); "narrative" writes summaries; "investigation"
# runs the tool-calling deep investigations.
LLM_ROLES = ("planner", "narrative", "investigation", "critic")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULTS_FILE = "defaults.toml"

# Secrets: environment only, never in defaults.toml. Field -> variables, first set wins.
_SECRETS = {
    "groq_api_key": ("GROQ_API_KEY",),
    "openai_api_key": ("OPENAI_API_KEY",),
    "anthropic_api_key": ("ANTHROPIC_API_KEY",),
    "github_token": ("GH_TOKEN", "GITHUB_TOKEN"),
}
# Values normalized after reading, so `MODEL_PROVIDER=OpenAI` works.
_NORMALIZE = {
    "model_provider": str.lower,
    "log_level": str.upper,
    "log_format": str.lower,
    "store_backend": str.lower,
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _plain(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def _load_defaults() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The file's settings (sections flattened) and its per-provider tables."""
    text = resources.files("drrepo").joinpath(DEFAULTS_FILE).read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigurationError(f"{DEFAULTS_FILE}: {e}") from e
    providers = data.pop("providers", {})
    settings: dict[str, Any] = {}
    for section, table in data.items():
        if not isinstance(table, dict):
            raise ConfigurationError(f"{DEFAULTS_FILE}: {section!r} must be a [section]")
        for key, value in table.items():
            if key in settings:
                raise ConfigurationError(f"{DEFAULTS_FILE}: {key!r} is set twice")
            settings[key] = _plain(value)
    profiles = {
        name: {key: _plain(value) for key, value in table.items()}
        for name, table in providers.items()
    }
    return settings, profiles


_DEFAULTS, _PROVIDER_DEFAULTS = _load_defaults()


def _default(name: str) -> Any:
    try:
        return _DEFAULTS[name]
    except KeyError:
        raise ConfigurationError(f"{DEFAULTS_FILE} has no {name!r} setting") from None


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


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated values, stripped; empty entries dropped."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(v.strip() for v in raw.split(",") if v.strip())


def _env_value(name: str, default: Any) -> Any:
    """`name` from the environment, parsed like `default` (bool before int: bool is an int)."""
    if isinstance(default, bool):
        return _env_bool(name, default)
    if isinstance(default, int):
        return _env_int(name, default)
    if isinstance(default, float):
        return _env_float(name, default)
    if isinstance(default, tuple):
        return _env_list(name, default)
    return _env_str(name, default)


@dataclass(frozen=True)
class Config:
    """Application configuration. Build via `Config.from_env()` or directly for tests.

    Defaults (and what each setting does) are in `defaults.toml`."""

    # API keys (kept out of repr, so a logged or printed Config never shows them)
    groq_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)
    github_token: str = field(default="", repr=False)

    # [llm]
    model_provider: str = _default("model_provider")
    model_name: str = _default("model_name")
    model_name_planner: str = _default("model_name_planner")
    model_name_narrative: str = _default("model_name_narrative")
    model_name_investigation: str = _default("model_name_investigation")
    model_name_critic: str = _default("model_name_critic")
    ollama_base_url: str = _default("ollama_base_url")
    temperature: float = _default("temperature")
    max_tokens: int = _default("max_tokens")
    llm_request_timeout_seconds: int = _default("llm_request_timeout_seconds")

    # [logging]
    log_level: str = _default("log_level")
    log_format: str = _default("log_format")

    # [clone]
    clone_timeout_seconds: int = _default("clone_timeout_seconds")
    clone_max_size_mb: int = _default("clone_max_size_mb")
    clone_cache_ttl_seconds: int = _default("clone_cache_ttl_seconds")
    clone_cache_max_mb: int = _default("clone_cache_max_mb")
    clone_cache_dir: str = _default("clone_cache_dir")

    # [scanners]
    enable_scanner_limits: bool = _default("enable_scanner_limits")
    scanner_file_size_mb: int = _default("scanner_file_size_mb")
    scanner_memory_mb: int = _default("scanner_memory_mb")
    collector_timeout_seconds: int = _default("collector_timeout_seconds")

    # [collectors]
    enable_semgrep: bool = _default("enable_semgrep")
    enable_bandit: bool = _default("enable_bandit")
    enable_dependency_audit: bool = _default("enable_dependency_audit")
    enable_license_audit: bool = _default("enable_license_audit")
    enable_maintenance_audit: bool = _default("enable_maintenance_audit")
    enable_complexity_metrics: bool = _default("enable_complexity_metrics")
    enable_workflow_audit: bool = _default("enable_workflow_audit")
    enable_dockerfile_audit: bool = _default("enable_dockerfile_audit")
    enable_scorecard: bool = _default("enable_scorecard")
    scan_history_commits: int = _default("scan_history_commits")
    license_deny: tuple[str, ...] = _default("license_deny")
    license_allow: tuple[str, ...] = _default("license_allow")

    # [investigation]
    enable_deep_investigation: bool = _default("enable_deep_investigation")
    enable_llm_judgment: bool = _default("enable_llm_judgment")
    enable_agent_critic: bool = _default("enable_agent_critic")
    enable_mcp_tools: bool = _default("enable_mcp_tools")
    max_tool_calls_per_investigator: int = _default("max_tool_calls_per_investigator")
    investigator_timeout_seconds: int = _default("investigator_timeout_seconds")
    llm_max_parallel_investigations: int = _default("llm_max_parallel_investigations")
    investigation_context_tokens: int = _default("investigation_context_tokens")

    # [circuit_breaker]
    enable_llm_circuit_breaker: bool = _default("enable_llm_circuit_breaker")
    llm_circuit_breaker_threshold: int = _default("llm_circuit_breaker_threshold")
    llm_circuit_breaker_timeout_seconds: int = _default("llm_circuit_breaker_timeout_seconds")

    # [budget]
    enable_llm_budget_tracking: bool = _default("enable_llm_budget_tracking")
    llm_token_budget_per_run: int = _default("llm_token_budget_per_run")
    estimated_tokens_per_deep_investigation: int = _default(
        "estimated_tokens_per_deep_investigation"
    )

    # [cache]
    enable_dependency_lookup_cache: bool = _default("enable_dependency_lookup_cache")

    # [suppressions]
    suppressions_file: str = _default("suppressions_file")
    trust_repo_suppressions: bool = _default("trust_repo_suppressions")

    # [store]
    enable_score_history: bool = _default("enable_score_history")
    store_backend: str = _default("store_backend")
    store_path: str = _default("store_path")

    # [api]
    api_workers: int = _default("api_workers")
    api_max_queued: int = _default("api_max_queued")

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
        if self.store_backend not in STORE_BACKENDS:
            problems.append(
                f"STORE_BACKEND={self.store_backend!r} is not one of {', '.join(STORE_BACKENDS)}"
            )
        if self.log_format not in ("text", "json"):
            problems.append(f"LOG_FORMAT={self.log_format!r} is not text or json")
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
        """Load configuration from environment variables (and `env_file` if present)
        over the defaults in `defaults.toml`.

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

        provider = _env_str("MODEL_PROVIDER", _DEFAULTS["model_provider"]).lower()
        defaults = {**_DEFAULTS, **_PROVIDER_DEFAULTS.get(provider, {})}
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in _SECRETS:
                values[f.name] = next(
                    (v for name in _SECRETS[f.name] if (v := _env_str(name, ""))), ""
                )
                continue
            value = _env_value(f.name.upper(), defaults[f.name])
            values[f.name] = _NORMALIZE[f.name](value) if f.name in _NORMALIZE else value
        return cls(**values)

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
        "investigation_context_tokens",
        "api_workers",
        "api_max_queued",
        "clone_cache_max_mb",
    }
)
_MUST_BE_NON_NEGATIVE = frozenset(
    {
        "llm_circuit_breaker_timeout_seconds",
        "llm_token_budget_per_run",
        "scan_history_commits",
        "llm_max_parallel_investigations",
        "clone_cache_ttl_seconds",
        "scanner_file_size_mb",
        "scanner_memory_mb",
    }
)
_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "tuple[str, ...]": (tuple,),
}


def _check_defaults() -> None:
    """`defaults.toml` sets exactly the non-secret settings, each with the right type,
    and its provider tables name known providers and settings."""
    settings = {f.name: str(f.type) for f in fields(Config) if f.name not in _SECRETS}
    problems = [f"unknown setting {k!r}" for k in _DEFAULTS.keys() - settings.keys()]
    for name, table in _PROVIDER_DEFAULTS.items():
        if name not in SUPPORTED_PROVIDERS:
            problems.append(f"[providers.{name}] is not a supported provider")
        problems += [
            f"[providers.{name}] unknown setting {k!r}" for k in table.keys() - settings.keys()
        ]
    tables = [("", _DEFAULTS)]
    tables += [(f"[providers.{p}] ", t) for p, t in _PROVIDER_DEFAULTS.items()]
    for source, table in tables:
        for key, value in table.items():
            expected = _TYPES.get(settings.get(key, ""), ())
            is_bool = isinstance(value, bool)
            if expected and (not isinstance(value, expected) or (is_bool and bool not in expected)):
                problems.append(f"{source}{key} = {value!r} should be {settings[key]}")
    if problems:
        raise ConfigurationError(f"{DEFAULTS_FILE}: " + "; ".join(problems))


_check_defaults()
