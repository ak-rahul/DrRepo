import dataclasses

import pytest

from drrepo import config as config_module
from drrepo.config import Config
from drrepo.errors import ConfigurationError

_ENV_KEYS = [
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "MODEL_PROVIDER",
    "ENABLE_DEEP_INVESTIGATION",
    "MAX_TOOL_CALLS_PER_INVESTIGATOR",
    "LLM_TOKEN_BUDGET_PER_RUN",
    "TEMPERATURE",
    "LOG_LEVEL",
    "LLM_MAX_PARALLEL_INVESTIGATIONS",
    "INVESTIGATION_CONTEXT_TOKENS",
    "INVESTIGATOR_TIMEOUT_SECONDS",
    "LICENSE_DENY",
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return str(tmp_path / "missing.env")


def test_defaults_without_env_are_the_file_plus_the_provider_table(clean_env):
    config = Config.from_env(env_file=clean_env)
    groq = config_module._PROVIDER_DEFAULTS["groq"]
    assert config == dataclasses.replace(Config(), **groq)
    assert config.llm_max_parallel_investigations == 1
    assert config.investigation_context_tokens == 7000


def test_config_defaults_come_from_the_defaults_file():
    defaults = config_module._DEFAULTS
    config = Config()
    for f in dataclasses.fields(Config):
        if f.name not in config_module._SECRETS:
            assert getattr(config, f.name) == defaults[f.name], f.name
    # Secrets never live in the file.
    assert not defaults.keys() & config_module._SECRETS.keys()


def test_provider_table_applies_only_to_its_provider(clean_env, monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    config = Config.from_env(env_file=clean_env)
    assert config.investigation_context_tokens == Config().investigation_context_tokens


def test_environment_wins_over_the_provider_table(clean_env, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_CONTEXT_TOKENS", "20000")
    monkeypatch.setenv("LICENSE_DENY", "GPL-3.0, AGPL-3.0,")
    config = Config.from_env(env_file=clean_env)
    assert config.investigation_context_tokens == 20000
    assert config.license_deny == ("GPL-3.0", "AGPL-3.0")


@pytest.mark.parametrize(
    ("defaults", "providers", "message"),
    [
        ({"surprise": 1}, {}, "unknown setting 'surprise'"),
        ({"max_tokens": "2000"}, {}, "max_tokens = '2000' should be int"),
        ({"enable_semgrep": 1}, {}, "enable_semgrep = 1 should be bool"),
        ({"max_tokens": True}, {}, "max_tokens = True should be int"),
        ({}, {"mistral": {}}, "not a supported provider"),
        ({}, {"groq": {"max_token": 1}}, "unknown setting 'max_token'"),
    ],
)
def test_defaults_file_is_checked(monkeypatch, defaults, providers, message):
    monkeypatch.setattr(config_module, "_DEFAULTS", {**config_module._DEFAULTS, **defaults})
    monkeypatch.setattr(config_module, "_PROVIDER_DEFAULTS", providers)
    with pytest.raises(ConfigurationError, match=message):
        config_module._check_defaults()


def test_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", " key ")
    monkeypatch.setenv("ENABLE_DEEP_INVESTIGATION", "no")
    monkeypatch.setenv("MAX_TOOL_CALLS_PER_INVESTIGATOR", "3")
    monkeypatch.setenv("TEMPERATURE", "0.7")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("MODEL_PROVIDER", "OpenAI")
    config = Config.from_env(env_file=clean_env)
    assert config.groq_api_key == "key"
    assert config.enable_deep_investigation is False
    assert config.max_tool_calls_per_investigator == 3
    assert config.temperature == 0.7
    assert config.log_level == "DEBUG"
    assert config.model_provider == "openai"


def test_github_token_fallback(clean_env, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-actions")
    assert Config.from_env(env_file=clean_env).github_token == "from-actions"


def test_reads_dotenv_file(clean_env, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=from-file\n", encoding="utf-8")
    try:
        assert Config.from_env(env_file=str(env_file)).groq_api_key == "from-file"
    finally:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ENABLE_DEEP_INVESTIGATION", "maybe", "not a boolean"),
        ("MAX_TOOL_CALLS_PER_INVESTIGATOR", "many", "not an integer"),
        ("TEMPERATURE", "hot", "not a number"),
        ("MODEL_PROVIDER", "anthropic-ish", "not supported"),
    ],
)
def test_invalid_values_raise(clean_env, monkeypatch, key, value, message):
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigurationError, match=message):
        Config.from_env(env_file=clean_env)


@pytest.mark.parametrize(
    ("provider", "kwargs", "missing"),
    [
        ("groq", {}, ["GROQ_API_KEY"]),
        ("openai", {}, ["OPENAI_API_KEY"]),
        ("groq", {"groq_api_key": "x"}, []),
        ("openai", {"openai_api_key": "x"}, []),
    ],
)
def test_validate_for_llm(provider, kwargs, missing):
    assert Config(model_provider=provider, **kwargs).validate_for_llm() == missing


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"llm_circuit_breaker_threshold": 0}, "LLM_CIRCUIT_BREAKER_THRESHOLD=0"),
        ({"clone_timeout_seconds": -5}, "CLONE_TIMEOUT_SECONDS=-5"),
        ({"llm_token_budget_per_run": -1}, "LLM_TOKEN_BUDGET_PER_RUN=-1"),
        ({"temperature": 3.0}, "TEMPERATURE"),
        ({"log_level": "LOUD"}, "LOG_LEVEL"),
    ],
)
def test_out_of_range_values_are_rejected_at_construction(kwargs, message):
    with pytest.raises(ConfigurationError, match=message):
        Config(**kwargs)


def test_config_is_frozen_and_replace_revalidates():
    config = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.enable_semgrep = False  # type: ignore[misc]
    assert dataclasses.replace(config, enable_semgrep=False).enable_semgrep is False
    with pytest.raises(ConfigurationError):
        dataclasses.replace(config, max_tokens=0)


def test_zero_budget_is_allowed():
    assert Config(llm_token_budget_per_run=0).llm_token_budget_per_run == 0


def test_env_local_wins_over_env_and_real_variables_win_over_both(tmp_path, monkeypatch):
    for name in ("MODEL_NAME", "LOG_LEVEL"):
        monkeypatch.setenv(name, "x")  # remembered, so teardown restores the original state
        monkeypatch.delenv(name)
    (tmp_path / ".env").write_text("MODEL_NAME=from-env\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("MODEL_NAME=from-local\n", encoding="utf-8")
    config = Config.from_env(env_file=str(tmp_path / ".env"))
    assert config.model_name == "from-local" and config.log_level == "DEBUG"

    monkeypatch.setenv("MODEL_NAME", "from-shell")
    assert Config.from_env(env_file=str(tmp_path / ".env")).model_name == "from-shell"
