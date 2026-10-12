"""Host header allow-list (TrustedHostMiddleware): which Host headers reach the API, per environment."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

PUBLIC_HOST = "insightflow.example.org"  # example.org is reserved for documentation (RFC 2606)


def settings(tmp_path: Path, **values) -> Settings:
    return Settings(data_dir=tmp_path / "data", _env_file=None, **values)


def status_for_host(app, host: str) -> int:
    return TestClient(app).get("/api/health", headers={"Host": host}).status_code


# ---------- Development defaults ----------


@pytest.mark.parametrize(
    "host",
    [
        "localhost:5180",  # the Vite dev server forwards the browser's Host header
        "localhost",
        "127.0.0.1:8000",  # opening the API directly, as the README does
        "[::1]:8000",
        "testserver",  # Starlette's TestClient
    ],
)
def test_local_hosts_are_allowed_by_default_outside_production(tmp_path: Path, host: str) -> None:
    assert status_for_host(create_app(settings(tmp_path)), host) == 200


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "127.0.0.1.nip.io", "0.0.0.0"])
def test_other_hosts_are_rejected_by_default(tmp_path: Path, host: str) -> None:
    response = TestClient(create_app(settings(tmp_path))).get("/api/health", headers={"Host": host})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


# ---------- Production ----------


def production(tmp_path: Path, hosts: str | list[str] = f"{PUBLIC_HOST},127.0.0.1") -> Settings:
    return settings(tmp_path, app_env="production", allowed_hosts=hosts)


@pytest.mark.parametrize("host", [PUBLIC_HOST, f"{PUBLIC_HOST}:443", "127.0.0.1:8000"])
def test_production_allows_only_the_configured_hosts(tmp_path: Path, host: str) -> None:
    assert status_for_host(create_app(production(tmp_path)), host) == 200


@pytest.mark.parametrize(
    "host",
    ["localhost", "testserver", "evil.example", f"www.{PUBLIC_HOST}", f"{PUBLIC_HOST}.evil.example", f"x.{PUBLIC_HOST}"],
)
def test_production_rejects_every_other_host(tmp_path: Path, host: str) -> None:
    assert status_for_host(create_app(production(tmp_path)), host) == 400


def test_production_never_redirects_to_a_www_host(tmp_path: Path) -> None:
    app = create_app(production(tmp_path, hosts=f"www.{PUBLIC_HOST}"))

    response = TestClient(app).get("/api/health", headers={"Host": PUBLIC_HOST}, follow_redirects=False)

    assert response.status_code == 400  # Starlette would otherwise answer with a redirect to www.


def test_production_requires_an_explicit_host_list(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        settings(tmp_path, app_env="production")


@pytest.mark.parametrize("hosts", ["*", f"*.{PUBLIC_HOST}", f"{PUBLIC_HOST},*"])
def test_production_refuses_wildcards(tmp_path: Path, hosts: str) -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        production(tmp_path, hosts=hosts)


@pytest.mark.parametrize(
    "hosts",
    [
        "",
        " , ",
        f"{PUBLIC_HOST}:443",  # ports are not part of the match
        f"https://{PUBLIC_HOST}",
        f"{PUBLIC_HOST}/api",
        "INSIGHTFLOW_HOSTNAME",  # the deployment template's placeholder must never start a server
        "bad_host.example.org",
        "-bad.example.org",
        "[not-an-ip]",
    ],
)
def test_invalid_host_entries_stop_the_server_at_startup(tmp_path: Path, hosts: str) -> None:
    for app_env in ("development", "production"):
        with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
            settings(tmp_path, app_env=app_env, allowed_hosts=hosts)


def test_host_list_is_read_from_a_comma_separated_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", " Insightflow.Example.org , 127.0.0.1,[::1] ")

    configured = Settings(data_dir=tmp_path / "data", _env_file=None)

    assert configured.trusted_hosts == [PUBLIC_HOST, "127.0.0.1", "[::1]"]


def test_an_unknown_host_is_refused_before_the_body_is_read(tmp_path: Path) -> None:
    """The host check is the outermost layer, so a request for another site never reaches the upload limit."""
    app = create_app(production(tmp_path))
    chunks_read = 0

    async def receive():
        nonlocal chunks_read
        chunks_read += 1
        return {"type": "http.request", "body": b"x", "more_body": False}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/uploads/csv", "raw_path": b"/api/uploads/csv", "query_string": b"", "root_path": "",
        "headers": [(b"host", b"evil.example"), (b"content-length", str(500 * 1024 * 1024).encode())],
        "client": ("127.0.0.1", 1), "server": ("evil.example", 80),
    }

    asyncio.run(app(scope, receive, send))

    assert sent[0]["status"] == 400
    assert chunks_read == 0
