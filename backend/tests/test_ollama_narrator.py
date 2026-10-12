"""The Ollama adapter against a stand-in HTTP server on localhost. No model and no internet needed."""

import importlib
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.narration import ollama
from app.narration.ollama import OllamaNarrator
from app.narration.providers import NarratorError


class FakeOllama(BaseHTTPRequestHandler):
    """Answers like Ollama's /api/generate and /api/tags. Behavior is set on the server object."""

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def do_GET(self) -> None:
        self.server.seen.append(f"GET {self.path}")
        if self.server.redirect:
            return self._redirect()
        self._reply(200, {"models": [{"name": name} for name in self.server.models]})

    def do_POST(self) -> None:
        self.server.seen.append(f"POST {self.path}")
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        if self.server.redirect:
            return self._redirect()
        time.sleep(self.server.delay)
        if self.server.fail:
            self._reply(500, {"error": "model 'x' not found"})
        else:
            self._reply(200, {"model": body["model"], "response": "  Revenue was 120.00 in March 2026.  ", "done": True})

    def _redirect(self) -> None:
        code, location = self.server.redirect
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    httpd.requests, httpd.seen, httpd.models, httpd.delay, httpd.fail, httpd.redirect = [], [], ["llama3.2:3b"], 0.0, False, None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    httpd = start_server()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def proxy() -> Iterator[ThreadingHTTPServer]:
    """A stand-in proxy: anything that reaches it would have left through a proxy."""
    httpd = start_server()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def url_of(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_write_sends_the_prompt_without_streaming_and_returns_the_text(server) -> None:
    narrator = OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=5)

    text = narrator.write("SYSTEM RULES", "DATA")

    assert text == "Revenue was 120.00 in March 2026."
    sent = server.requests[0]
    assert (sent["model"], sent["system"], sent["prompt"], sent["stream"]) == ("llama3.2:3b", "SYSTEM RULES", "DATA", False)
    assert sent["options"]["temperature"] == 0


def test_an_error_answer_is_reported(server) -> None:
    server.fail = True

    with pytest.raises(NarratorError, match="HTTP 500"):
        OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=5).write("s", "p")


def test_a_slow_answer_times_out(server) -> None:
    server.delay = 1.0

    with pytest.raises(NarratorError, match="did not answer within 0.2 seconds"):
        OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=0.2).write("s", "p")


def test_an_unreachable_ollama_is_reported() -> None:
    with pytest.raises(NarratorError, match="Could not reach Ollama"):
        OllamaNarrator("http://127.0.0.1:9", "llama3.2:3b", timeout_seconds=5).write("s", "p")


def test_status_reports_an_installed_model(server) -> None:
    status = OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=5).status()

    assert (status.enabled, status.available, status.provider, status.model, status.reason) == (True, True, "ollama", "llama3.2:3b", None)


def test_status_reports_a_missing_model_with_the_fix(server) -> None:
    status = OllamaNarrator(url_of(server), "qwen2.5:3b", timeout_seconds=5).status()

    assert status.available is False
    assert status.reason == "The model 'qwen2.5:3b' is not installed. Run: ollama pull qwen2.5:3b"


def test_status_reports_ollama_not_running() -> None:
    status = OllamaNarrator("http://127.0.0.1:9", "llama3.2:3b", timeout_seconds=5).status()

    assert status.available is False
    assert "Ollama is not running" in status.reason
    assert "127.0.0.1" not in status.reason and "http" not in status.reason  # messages never carry addresses


# ---------- Findings never leave this computer (audit F1) ----------


@pytest.mark.parametrize("variable", ["HTTP_PROXY", "http_proxy", "ALL_PROXY", "HTTPS_PROXY"])
def test_proxy_settings_are_ignored(server, proxy, monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, url_of(proxy))
    # Proxy settings are read when an opener is built, so reload the module as a server
    # started with this variable already set would load it.
    fresh = importlib.reload(ollama)
    try:
        narrator = fresh.OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=5)

        assert narrator.status().available is True
        assert narrator.write("SYSTEM", "DATA") == "Revenue was 120.00 in March 2026."
        assert proxy.seen == []  # nothing went through the proxy
        assert server.seen == ["GET /api/tags", "POST /api/generate"]
    finally:
        monkeypatch.undo()
        importlib.reload(ollama)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirects_are_refused(server, proxy, code: int) -> None:
    server.redirect = (code, f"{url_of(proxy)}/elsewhere")
    narrator = OllamaNarrator(url_of(server), "llama3.2:3b", timeout_seconds=5)

    with pytest.raises(NarratorError, match="redirect"):
        narrator.write("SYSTEM", "DATA")
    status = narrator.status()

    assert status.available is False
    assert proxy.seen == []  # the redirect target was never contacted
