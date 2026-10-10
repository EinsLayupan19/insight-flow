from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.main import create_app


def make_client(settings: Settings | None = None) -> TestClient:
    app = create_app()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_health_returns_ok() -> None:
    response = make_client().get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "InsightFlow AI"
    assert body["version"] == __version__


def test_health_reports_environment_from_settings() -> None:
    settings = Settings(app_env="test", _env_file=None)

    response = make_client(settings).get("/api/health")

    assert response.json()["environment"] == "test"


def test_health_never_exposes_api_key() -> None:
    settings = Settings(gemini_api_key="super-secret-test-key", _env_file=None)

    response = make_client(settings).get("/api/health")

    assert "super-secret-test-key" not in response.text
    assert "gemini" not in response.text.lower()


def test_unknown_route_returns_404() -> None:
    response = make_client().get("/api/does-not-exist")

    assert response.status_code == 404
