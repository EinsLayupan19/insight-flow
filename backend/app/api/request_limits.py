"""Request body size limit, enforced while the body is received (audit F4).

Starlette writes every uploaded file part to a temporary file before a route runs, with no size
limit of its own, so the upload check in csv_upload.py alone only runs after the whole body is on
disk. This ASGI middleware stops a request first:
- a declared Content-Length over the limit is answered with 413 before any body is read;
- a body without a length (chunked) is counted as it arrives and cut off with 413 once it passes
  the limit, so the rest is never read or stored.
The limit is the upload limit plus a small allowance for the multipart framing and form fields;
files just over the upload limit still reach the route's own check and get the same message.
"""

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MULTIPART_ALLOWANCE = 256 * 1024  # boundaries, part headers, and the short column-mapping fields


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int, message: str) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.message = message

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._too_large(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body parsing, so the route answers 413.
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, self.message)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except HTTPException as error:
            # Only reached if the body was read outside a FastAPI route; answer if nothing was sent yet.
            if error.status_code != status.HTTP_413_CONTENT_TOO_LARGE or started:
                raise
            await self._too_large(scope, receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": self.message}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            return int(value) if value.isdigit() else None  # malformed lengths are left to the server
    return None
