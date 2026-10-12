"""Request handling under load: parsing off the event loop (audit F3) and body size limits while receiving (F4)."""

import asyncio
import time
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.api import csv_upload
from app.config import Settings
from app.main import create_app

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_sales.csv").read_bytes()
IN_MEMORY_ENDPOINTS = [
    "/api/uploads/csv",
    "/api/uploads/csv/profile",
    "/api/uploads/csv/metrics",
    "/api/uploads/csv/trends",
    "/api/uploads/csv/performance",
    "/api/uploads/csv/insights",
]
MB = 1024 * 1024


def settings(tmp_path: Path, max_upload_mb: int = 10) -> Settings:
    return Settings(data_dir=tmp_path / "data", max_upload_mb=max_upload_mb, _env_file=None)


# ---------- F3: parsing never runs on the event loop ----------


@pytest.mark.parametrize("url", IN_MEMORY_ENDPOINTS)
def test_csv_parsing_runs_in_a_worker_thread(url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    where: list[str] = []
    real_parse = csv_upload.parse_csv

    def spy(content: bytes):
        try:
            asyncio.get_running_loop()
            where.append("event loop")
        except RuntimeError:
            where.append("worker thread")
        return real_parse(content)

    monkeypatch.setattr(csv_upload, "parse_csv", spy)

    response = TestClient(create_app(settings(tmp_path))).post(url, files={"file": ("s.csv", SAMPLE, "text/csv")})

    assert response.status_code == 200
    assert where == ["worker thread"]


def test_the_health_check_answers_while_an_upload_is_being_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_parse = csv_upload.parse_csv

    def slow_parse(content: bytes):
        time.sleep(1.0)  # stands in for a large file
        return real_parse(content)

    monkeypatch.setattr(csv_upload, "parse_csv", slow_parse)

    async def scenario() -> tuple[int, float, bool]:
        transport = httpx2.ASGITransport(app=create_app(settings(tmp_path)))
        # "testserver" is one of the host names allowed outside production (ALLOWED_HOSTS unset).
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            upload = asyncio.create_task(client.post("/api/uploads/csv", files={"file": ("s.csv", SAMPLE, "text/csv")}))
            await asyncio.sleep(0.2)
            start = time.perf_counter()
            health = await client.get("/api/health")
            latency = time.perf_counter() - start
            still_parsing = not upload.done()
            assert (await upload).status_code == 200
            return health.status_code, latency, still_parsing

    status, latency, still_parsing = asyncio.run(scenario())

    assert status == 200
    assert still_parsing  # the health check was answered during the parse, not after it
    assert latency < 0.5


# ---------- F4: the body limit is enforced while the request is received ----------


async def call_asgi(app, headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> tuple[list[dict], int]:
    """Send one POST through the ASGI app; return what it sent back and how many body chunks it read."""
    read = 0
    sent: list[dict] = []

    async def receive() -> dict:
        nonlocal read
        if read < len(chunks):
            read += 1
            return {"type": "http.request", "body": chunks[read - 1], "more_body": read < len(chunks)}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/uploads/csv", "raw_path": b"/api/uploads/csv", "query_string": b"", "root_path": "",
        "headers": [(b"host", b"testserver"), *headers], "client": ("127.0.0.1", 1), "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return sent, read


def status_of(sent: list[dict]) -> int:
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def test_an_oversized_content_length_is_refused_before_any_body_is_read(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, max_upload_mb=1))
    headers = [(b"content-type", b"multipart/form-data; boundary=x"), (b"content-length", str(50 * MB).encode())]

    sent, read = asyncio.run(call_asgi(app, headers, [b"x" * 1024] * 10))

    assert status_of(sent) == 413
    assert read == 0  # nothing was received or buffered
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    assert b"The file is larger than the 1 MB limit." in body


def test_a_streamed_body_is_cut_off_as_soon_as_it_passes_the_limit(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, max_upload_mb=1))
    chunk = b"x" * (64 * 1024)
    chunks = [b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.csv\"\r\n\r\n"] + [chunk] * 80  # 5 MB, no length

    sent, read = asyncio.run(call_asgi(app, [(b"content-type", b"multipart/form-data; boundary=x")], chunks))

    assert status_of(sent) == 413
    assert read < 25  # stopped near 1 MB plus the allowance, long before the 81 chunks offered


def test_files_just_over_the_upload_limit_get_the_same_message(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path, max_upload_mb=1)))
    header = b"order_id,revenue\n"

    small_overshoot = client.post("/api/uploads/csv", files={"file": ("a.csv", header + b"1,2\n" * 270_000, "text/csv")})
    large_overshoot = client.post("/api/uploads/csv", files={"file": ("a.csv", header + b"1,2\n" * 1_000_000, "text/csv")})

    assert small_overshoot.status_code == large_overshoot.status_code == 413
    assert small_overshoot.json()["detail"] == large_overshoot.json()["detail"] == "The file is larger than the 1 MB limit."


def test_uploads_within_the_limit_still_work(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path, max_upload_mb=1)))

    response = client.post("/api/uploads/csv", files={"file": ("s.csv", SAMPLE, "text/csv")})

    assert response.status_code == 200
    assert client.post("/api/datasets", files={"file": ("s.csv", SAMPLE, "text/csv")}).status_code == 201
