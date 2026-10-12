"""Ollama on this computer, through its HTTP API. Uses only the standard library: no new dependency.

The URL is checked in Settings to point at this machine (localhost). That alone is not enough:
urllib normally sends requests through any proxy named in HTTP_PROXY and follows redirects, either
of which could carry the findings elsewhere. This adapter therefore uses its own opener with no
proxies and refuses every redirect. Requests are not streamed and use temperature 0.
"""

import json
import socket
import urllib.error
import urllib.request

from app.narration.providers import NarratorError, NarratorStatus

MAX_REPLY_BYTES = 64 * 1024
STATUS_TIMEOUT_SECONDS = 5


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib's signature
        raise NarratorError(f"Ollama answered with a redirect (HTTP {code}). Redirects are refused, so findings stay on this computer.")


# No ProxyHandler entries: HTTP_PROXY, http_proxy, and system proxy settings are ignored.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects())


class OllamaNarrator:
    provider = "ollama"

    def __init__(self, url: str, model: str, timeout_seconds: float) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def write(self, system: str, prompt: str) -> str:
        body = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_predict": 300},
        }
        reply = self._request("/api/generate", body, self.timeout_seconds)
        text = reply.get("response")
        if not isinstance(text, str):
            raise NarratorError("Ollama sent an answer without text.")
        return text.strip()

    def status(self) -> NarratorStatus:
        def unavailable(reason: str) -> NarratorStatus:
            return NarratorStatus(enabled=True, provider=self.provider, model=self.model, available=False, reason=reason)

        try:
            tags = self._request("/api/tags", None, min(self.timeout_seconds, STATUS_TIMEOUT_SECONDS))
        except NarratorError:
            return unavailable("Ollama is not running on this computer. Start it (for example: ollama serve) and try again.")
        names = {model.get("name") for model in tags.get("models", []) if isinstance(model, dict)}
        wanted = {self.model} if ":" in self.model else {self.model, f"{self.model}:latest"}
        if not names & wanted:
            return unavailable(f"The model '{self.model}' is not installed. Run: ollama pull {self.model}")
        return NarratorStatus(enabled=True, provider=self.provider, model=self.model, available=True, reason=None)

    def _request(self, path: str, body: dict | None, timeout: float) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.url + path, data=data, method="GET" if body is None else "POST", headers={"Content-Type": "application/json"}
        )
        try:
            with _OPENER.open(request, timeout=timeout) as response:  # URL checked to be localhost; no proxy, no redirect
                raw = response.read(MAX_REPLY_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise NarratorError(f"Ollama answered with an error (HTTP {error.code}).") from error
        except (TimeoutError, socket.timeout) as error:
            raise NarratorError(f"Ollama did not answer within {timeout:g} seconds.") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise NarratorError(f"Ollama did not answer within {timeout:g} seconds.") from error
            raise NarratorError("Could not reach Ollama on this computer. Is it running?") from error
        if len(raw) > MAX_REPLY_BYTES:
            raise NarratorError("Ollama's answer was unexpectedly long.")
        try:
            reply = json.loads(raw)
        except ValueError as error:
            raise NarratorError("Ollama sent an answer that is not valid JSON.") from error
        if not isinstance(reply, dict):
            raise NarratorError("Ollama sent an unexpected answer.")
        return reply
