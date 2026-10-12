"""Cross-site request protection: state-changing requests that another website makes a browser send are refused.

The owner signs in at the reverse proxy, and browsers attach those credentials to any request to the site, so
the API itself refuses requests whose Sec-Fetch-Site or Origin header shows they came from somewhere else.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PUBLIC_HOST = "insightflow.example.org"
SITE = f"https://{PUBLIC_HOST}"
SAMPLE = (Path(__file__).parent / "fixtures" / "sample_sales.csv").read_bytes()
CATALOG = (Path(__file__).parent / "fixtures" / "catalog_sales.csv").read_bytes()
REFUSED = "This request came from another website, so InsightFlow refused it. Open InsightFlow directly and try again."
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def production_app(tmp_path: Path):
    """As behind nginx: public host name, HTTPS (Uvicorn takes the scheme from X-Forwarded-Proto)."""
    return create_app(
        Settings(app_env="production", allowed_hosts=f"{PUBLIC_HOST},127.0.0.1", data_dir=tmp_path / "data", _env_file=None)
    )


@pytest.fixture
def site(tmp_path: Path) -> TestClient:
    """The production app with one saved dataset (id 1) and one recorded analysis (id 1)."""
    client = TestClient(production_app(tmp_path), base_url=SITE)
    assert client.post("/api/datasets", files={"file": ("sample.csv", SAMPLE, "text/csv")}).status_code == 201
    assert client.post("/api/datasets/1/analyses", json={"kind": "profile"}).status_code == 201
    return client


def state_changing_routes(app) -> list[tuple[str, str]]:
    """Every endpoint with a method other than GET, HEAD, or OPTIONS, with its path parameters filled in.

    Read from the app's OpenAPI schema (generated even when the docs are switched off in production), so an
    endpoint added later is covered without editing this function.
    """
    found = [
        (method.upper(), path.replace("{dataset_id}", "1").replace("{analysis_id}", "1"))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() in UNSAFE_METHODS
    ]
    assert found, "no state-changing endpoints found: the tests below would check nothing"
    return found


def dataset_names(client: TestClient) -> list[str]:
    return [dataset["filename"] for dataset in client.get("/api/datasets").json()["datasets"]]


# ---------- Every state-changing endpoint ----------


def test_the_api_has_the_expected_state_changing_endpoints(tmp_path: Path) -> None:
    """If an endpoint is added, it is covered by the tests below automatically; this list keeps them honest."""
    assert sorted(state_changing_routes(production_app(tmp_path))) == sorted([
        ("POST", "/api/uploads/csv"),
        ("POST", "/api/uploads/csv/profile"),
        ("POST", "/api/uploads/csv/metrics"),
        ("POST", "/api/uploads/csv/trends"),
        ("POST", "/api/uploads/csv/performance"),
        ("POST", "/api/uploads/csv/insights"),
        ("POST", "/api/datasets"),
        ("DELETE", "/api/datasets/1"),
        ("POST", "/api/datasets/1/analyses"),
        ("POST", "/api/datasets/1/analyses/1/narrations"),
    ])


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    ],
    ids=["malicious Origin", "cross-site Fetch Metadata", "both"],
)
def test_every_state_changing_endpoint_refuses_cross_site_requests(site: TestClient, headers: dict[str, str]) -> None:
    for method, path in state_changing_routes(site.app):
        response = site.request(method, path, headers=headers, files={"file": ("other.csv", CATALOG, "text/csv")} if method == "POST" else None)
        assert (response.status_code, response.json()) == (403, {"detail": REFUSED}), (method, path)

    assert dataset_names(site) == ["sample.csv"]  # nothing was saved or deleted
    assert len(site.get("/api/datasets/1/analyses").json()["analyses"]) == 1  # nothing was recorded


# ---------- Which requests are refused ----------


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": f"http://{PUBLIC_HOST}"},  # same host, but not over HTTPS
        {"Origin": f"{SITE}:8443"},  # same host, other port
        {"Origin": f"https://www.{PUBLIC_HOST}"},
        {"Origin": f"https://{PUBLIC_HOST}.evil.example"},
        {"Origin": "null"},  # sandboxed frames, file: pages, some redirects
        {"Origin": "not a url"},
        {"Origin": f"{SITE}/api"},  # an origin never has a path
        {"Origin": f"https://user@{PUBLIC_HOST}"},
        {"Sec-Fetch-Site": "same-site"},  # another subdomain, such as someone else's *.duckdns.org site
        {"Sec-Fetch-Site": "cross-site", "Origin": SITE},  # each header is checked on its own
        {"Sec-Fetch-Site": "same-origin", "Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "something-new"},  # unknown values fail closed
    ],
)
def test_requests_from_other_origins_are_refused(site: TestClient, headers: dict[str, str]) -> None:
    response = site.delete("/api/datasets/1", headers=headers)

    assert response.status_code == 403
    assert site.get("/api/datasets/1").status_code == 200  # still there


# ---------- Which requests are allowed ----------


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": SITE, "Sec-Fetch-Site": "same-origin"},  # the InsightFlow page itself
        {"Origin": SITE},  # browsers without Fetch Metadata
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},  # started by the user (bookmark, address bar), never by another site
        {"Origin": f"{SITE}:443", "Sec-Fetch-Site": "same-origin"},  # the default port written out
        {"Origin": f"https://{PUBLIC_HOST.upper()}"},  # host names are case-insensitive
        {},  # no browser headers at all: curl, scripts, tests
    ],
    ids=["page", "origin only", "fetch metadata only", "user initiated", "explicit default port", "upper case", "non-browser"],
)
def test_same_origin_and_non_browser_requests_are_allowed(site: TestClient, headers: dict[str, str]) -> None:
    saved = site.post("/api/datasets", headers=headers, files={"file": ("catalog.csv", CATALOG, "text/csv")})
    analyzed = site.post("/api/datasets/1/analyses", headers=headers, json={"kind": "metrics"})
    in_memory = site.post("/api/uploads/csv", headers=headers, files={"file": ("sample.csv", SAMPLE, "text/csv")})
    deleted = site.delete("/api/datasets/1", headers=headers)

    assert (saved.status_code, analyzed.status_code, in_memory.status_code, deleted.status_code) == (201, 201, 200, 204)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reading_and_navigation_are_never_blocked(site: TestClient, method: str) -> None:
    """Links from other sites still open the app; browsers keep other sites from reading the answers."""
    response = site.request(method, "/api/datasets", headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})

    assert response.status_code != 403


def test_health_checks_without_browser_headers_work(tmp_path: Path) -> None:
    client = TestClient(production_app(tmp_path), base_url="http://127.0.0.1:8000")

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/ready").status_code == 200


def test_the_vite_development_proxy_counts_as_same_origin(tmp_path: Path) -> None:
    """In development the page is http://localhost:5180 and Vite forwards its Host header unchanged."""
    app = create_app(Settings(data_dir=tmp_path / "data", _env_file=None))
    client = TestClient(app, base_url="http://localhost:5180")
    page = {"Origin": "http://localhost:5180", "Sec-Fetch-Site": "same-origin"}

    assert client.post("/api/uploads/csv", headers=page, files={"file": ("s.csv", SAMPLE, "text/csv")}).status_code == 200
    other = {"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"}
    assert client.post("/api/uploads/csv", headers=other, files={"file": ("s.csv", SAMPLE, "text/csv")}).status_code == 403


def test_a_refused_request_is_answered_before_its_body_is_read(tmp_path: Path) -> None:
    app = production_app(tmp_path)
    chunks_read = 0
    sent: list[dict] = []

    async def receive():
        nonlocal chunks_read
        chunks_read += 1
        return {"type": "http.request", "body": b"x" * 1024, "more_body": chunks_read < 10}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/api/datasets", "raw_path": b"/api/datasets", "query_string": b"", "root_path": "",
        "headers": [(b"host", PUBLIC_HOST.encode()), (b"origin", b"https://evil.example"), (b"content-length", b"10240")],
        "client": ("127.0.0.1", 1), "server": (PUBLIC_HOST, 443),
    }
    asyncio.run(app(scope, receive, send))

    assert sent[0]["status"] == 403
    assert chunks_read == 0
