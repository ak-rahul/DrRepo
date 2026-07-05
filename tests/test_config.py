"""Tests for Config -- particularly that `from_env` never needs real
credentials to construct (only `validate_for_llm` reports what's missing)."""

from src.config import Config


class TestConfigFromEnv:
    def test_defaults_when_no_env_vars_set(self, monkeypatch, tmp_path):
        for key in (
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
            "GH_TOKEN",
            "MODEL_PROVIDER",
            "ENABLE_DEEP_INVESTIGATION",
            "MAX_TOOL_CALLS_PER_INVESTIGATOR",
        ):
            monkeypatch.delenv(key, raising=False)

        config = Config.from_env(env_file=str(tmp_path / "nonexistent.env"))

        assert config.groq_api_key == ""
        assert config.model_provider == "groq"
        assert config.enable_deep_investigation is True
        assert config.max_tool_calls_per_investigator == 8
        assert config.investigator_timeout_seconds == 90

    def test_env_vars_override_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GROQ_API_KEY", "real_key")
        monkeypatch.setenv("ENABLE_DEEP_INVESTIGATION", "false")
        monkeypatch.setenv("MAX_TOOL_CALLS_PER_INVESTIGATOR", "3")

        config = Config.from_env(env_file=str(tmp_path / "nonexistent.env"))

        assert config.groq_api_key == "real_key"
        assert config.enable_deep_investigation is False
        assert config.max_tool_calls_per_investigator == 3


class TestValidateForLlm:
    def test_missing_groq_key_reported(self):
        config = Config(model_provider="groq", groq_api_key="")
        assert config.validate_for_llm() == ["GROQ_API_KEY"]

    def test_missing_openai_key_reported(self):
        config = Config(model_provider="openai", openai_api_key="")
        assert config.validate_for_llm() == ["OPENAI_API_KEY"]

    def test_valid_config_reports_nothing_missing(self):
        config = Config(model_provider="groq", groq_api_key="present")
        assert config.validate_for_llm() == []
