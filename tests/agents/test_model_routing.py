"""Per-role model routing and provider construction."""

import sys
from types import SimpleNamespace

import pytest

from drrepo.agents.llm import LLMRuntime, TokenBudget, build_chat_model
from drrepo.config import DEFAULT_MODELS, Config
from drrepo.errors import ConfigurationError
from drrepo.resilience import CircuitBreaker
from drrepo.service import AnalysisService


def test_model_resolution_role_then_model_name_then_provider_default():
    assert Config().model_for() == DEFAULT_MODELS["groq"]
    assert (
        Config(model_provider="anthropic", anthropic_api_key="k").model_for("narrative")
        == DEFAULT_MODELS["anthropic"]
    )
    routed = Config(model_name="base", model_name_investigation="big")
    assert routed.models_by_role() == {
        "planner": "base",
        "narrative": "base",
        "investigation": "big",
        "critic": "base",
    }


def test_keys_per_provider():
    assert Config(model_provider="ollama").validate_for_llm() == []
    assert Config(model_provider="anthropic").validate_for_llm() == ["ANTHROPIC_API_KEY"]
    assert Config(model_provider="openai", openai_api_key="k").validate_for_llm() == []


def test_role_runtimes_share_breaker_and_budget():
    breaker, budget = CircuitBreaker(name="llm"), TokenBudget(100)
    main, big = object(), object()
    llm = LLMRuntime(
        client=main, breaker=breaker, budget=budget, role_clients={"investigation": big}
    )
    deep = llm.for_role("investigation")
    assert deep.client is big and deep.breaker is breaker and deep.budget is budget
    assert llm.for_role("narrative").client is main
    plain = LLMRuntime(client=main, budget=budget)
    assert plain.for_role("planner").client is main
    plain.for_role("critic").record_usage(None, "x" * 400)
    plain.for_role("investigation", label="investigation:security").record_usage(None, "x" * 40)
    assert budget.usage()["by_label"] == {"critic": 100, "investigation:security": 10}


def test_service_builds_one_client_per_distinct_model(monkeypatch, tmp_path):
    built = []

    def fake_build(config, model=None):
        built.append(model)
        return SimpleNamespace(model=model)

    monkeypatch.setattr("drrepo.service.build_chat_model", fake_build)
    config = Config(groq_api_key="k", model_name="base", model_name_investigation="big")
    service = AnalysisService(config, history_path=tmp_path / "h.json")
    assert sorted(built) == ["base", "big"]
    assert service.role_clients["planner"] is service.role_clients["narrative"]
    assert service.role_clients["investigation"].model == "big"
    assert service.llm_client.model == "base"


def test_optional_provider_without_its_extra_explains_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "langchain_anthropic", None)  # simulate "not installed"
    with pytest.raises(ConfigurationError, match="uv sync --extra anthropic"):
        build_chat_model(Config(model_provider="anthropic", anthropic_api_key="k"))


@pytest.mark.parametrize(
    ("provider", "module", "cls", "kwargs"),
    [
        ("anthropic", "langchain_anthropic", "ChatAnthropic", {"anthropic_api_key": "k"}),
        ("ollama", "langchain_ollama", "ChatOllama", {}),
    ],
)
def test_optional_providers_construct_with_retries_off(monkeypatch, provider, module, cls, kwargs):
    captured = {}

    def ctor(**params):
        captured.update(params)
        return SimpleNamespace(**params)

    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{cls: ctor}))
    build_chat_model(Config(model_provider=provider, **kwargs), "m")
    assert captured["model"] == "m"
    if provider == "anthropic":
        assert captured["max_retries"] == 0
    else:
        assert captured["base_url"] == "http://localhost:11434"


@pytest.mark.parametrize(
    ("provider", "module", "kwargs"),
    [
        ("anthropic", "langchain_anthropic", {"anthropic_api_key": "k"}),
        ("ollama", "langchain_ollama", {}),
    ],
)
def test_real_provider_classes_accept_our_arguments(provider, module, kwargs):
    """Catches an SDK renaming a constructor argument (CI installs all extras)."""
    pytest.importorskip(module)
    model = build_chat_model(Config(model_provider=provider, **kwargs), "some-model")
    assert type(model).__name__ in ("ChatAnthropic", "ChatOllama")
