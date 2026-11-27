import pytest

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
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return str(tmp_path / "missing.env")


def test_defaults_without_env(clean_env):
    config = Config.from_env(env_file=clean_env)
    assert config == Config()


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
    import dataclasses

    config = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.enable_semgrep = False  # type: ignore[misc]
    assert dataclasses.replace(config, enable_semgrep=False).enable_semgrep is False
    with pytest.raises(ConfigurationError):
        dataclasses.replace(config, max_tokens=0)


def test_zero_budget_is_allowed():
    assert Config(llm_token_budget_per_run=0).llm_token_budget_per_run == 0
