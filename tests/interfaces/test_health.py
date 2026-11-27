import httpx
import pytest
from fastapi.testclient import TestClient

from drrepo.config import Config
from drrepo.interfaces import health_api
from drrepo.interfaces.health_checks import check_all, check_github, check_llm
from tests.conftest import mock_http

GOOD = {
    "GET api.groq.com/openai/v1/models": {"data": [{"id": "llama-3.3-70b-versatile"}]},
    "GET api.github.com/rate_limit": {"resources": {"core": {"remaining": 4999, "limit": 5000}}},
    "POST api.osv.dev/v1/query": {"vulns": []},
}


def test_all_healthy():
    status = check_all(Config(groq_api_key="k", github_token="t"), client=mock_http(GOOD))
    assert status["status"] == "healthy"
    assert status["components"]["llm_groq"]["status"] == "up"
    assert status["components"]["github_api"]["extra"]["rate_limit_remaining"] == 4999


def test_missing_key_and_unknown_model_are_degraded_not_down():
    client = mock_http({**GOOD, "GET api.groq.com/openai/v1/models": {"data": [{"id": "other"}]}})
    assert check_llm(Config(groq_api_key="k"), client).status == "degraded"
    assert check_llm(Config(groq_api_key=""), client).status == "not_configured"


def test_rejected_key_is_down_and_unhealthy():
    client = mock_http({**GOOD, "GET api.groq.com/openai/v1/models": httpx.Response(401)})
    status = check_all(Config(groq_api_key="bad"), client=client)
    assert status["components"]["llm_groq"]["status"] == "down"
    assert status["status"] == "unhealthy"


def test_github_unauthenticated_works_with_note():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"resources": {"core": {"remaining": 30, "limit": 60}}})

    result = check_github(Config(github_token=""), mock_http({"GET rate_limit": handler}))
    assert seen["auth"] is None
    assert result.status == "degraded" and "unauthenticated" in result.detail


def test_network_error_is_down():
    def boom(_request):
        raise httpx.ConnectError("no route")

    result = check_github(Config(), mock_http({"GET rate_limit": boom}))
    assert result.status == "down" and "ConnectError" in result.detail


@pytest.fixture
def api(monkeypatch):
    health_api.get_config.cache_clear()
    monkeypatch.setattr(health_api, "get_config", lambda: Config(groq_api_key="k"))
    return TestClient(health_api.app)


def test_live_and_root(api):
    assert api.get("/health/live").text == "alive"
    assert "/health" in api.get("/").json()["endpoints"]


def test_ready(api, monkeypatch):
    assert api.get("/health/ready").json() == {"ready": True}
    monkeypatch.setattr(health_api, "get_config", lambda: Config(groq_api_key=""))
    response = api.get("/health/ready")
    assert response.status_code == 503 and response.json()["missing"] == ["GROQ_API_KEY"]


@pytest.mark.parametrize(
    ("overall", "code"), [("healthy", 200), ("degraded", 200), ("unhealthy", 503)]
)
def test_health_status_codes(api, monkeypatch, overall, code):
    monkeypatch.setattr(health_api, "check_all", lambda _c: {"status": overall, "components": {}})
    assert api.get("/health").status_code == code


def test_health_exception_is_503(api, monkeypatch):
    def boom(_c):
        raise RuntimeError("x")

    monkeypatch.setattr(health_api, "check_all", boom)
    response = api.get("/health")
    assert response.status_code == 503 and "RuntimeError" in response.json()["error"]
