"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""

import duckdb
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api import datasets, health, narration, uploads
from app.api.cross_site import CrossSiteRequestGuard
from app.api.csv_upload import BYTES_PER_MB
from app.api.request_limits import MULTIPART_ALLOWANCE, RequestBodyLimit
from app.config import Settings, get_settings

API_PREFIX = "/api"
OUT_OF_MEMORY_MESSAGE = (
    "This file needs more memory to analyze than the server allows (DUCKDB_MEMORY_LIMIT). "
    "Try a smaller file, or ask the administrator to raise the limit."
)


async def _out_of_memory(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse({"detail": OUT_OF_MEMORY_MESSAGE}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app from `settings` (tests) or from backend/.env.

    `settings` sets the docs, the body limit, and every route's settings dependency. The DuckDB
    limits are read from the process settings (get_settings) when each analysis starts.
    """
    configured = settings or get_settings()
    production = configured.app_env == "production"
    app = FastAPI(
        title="InsightFlow AI API",
        version=__version__,
        # The interactive docs describe every endpoint; they stay off in production.
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.add_middleware(
        RequestBodyLimit,
        max_bytes=configured.max_upload_mb * BYTES_PER_MB + MULTIPART_ALLOWANCE,
        message=f"The file is larger than the {configured.max_upload_mb} MB limit.",
    )
    # Middleware added later runs earlier. Order of checks: host name, then cross-site origin (it relies on the
    # checked Host header), then the body limit; refused requests are answered before their body is read.
    app.add_middleware(CrossSiteRequestGuard)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=configured.trusted_hosts, www_redirect=False)
    app.add_exception_handler(duckdb.OutOfMemoryException, _out_of_memory)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(datasets.router, prefix=API_PREFIX)
    app.include_router(narration.router, prefix=API_PREFIX)
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return app


app = create_app()
