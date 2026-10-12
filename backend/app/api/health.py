"""Health checks: liveness (the API is running) and readiness (it can store and read datasets)."""

import logging
import os
import tempfile
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app import __version__
from app.config import Settings, get_settings
from app.storage.database import database_path, load_migrations, open_database, schema_version

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    # Only safe, non-secret values are returned here.
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, str]  # "ok", or what failed (never a server path)
    schema_version: int | None


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A check failed; the reasons are in checks."}},
)
def readiness(settings: Annotated[Settings, Depends(get_settings)], response: Response) -> ReadinessResponse:
    """Open the database (applying any pending migrations, as every request does) and check DATA_DIR is writable.

    Nothing is deleted or changed except a uniquely named probe file, which is removed at once.
    """
    checks: dict[str, str] = {}
    version = None
    try:
        connection = open_database(database_path(settings.data_dir))
        try:
            connection.execute("SELECT 1").fetchone()
            version = schema_version(connection)
        finally:
            connection.close()
        checks["database"] = "ok" if version == len(load_migrations()) else "The database schema is not up to date."
    except Exception:  # any failure means not ready; details go to the server log only
        logger.exception("Readiness check: the database could not be opened")
        checks["database"] = "The database could not be opened."
    try:
        handle, probe = tempfile.mkstemp(prefix=".readiness-", dir=settings.data_dir)
        os.close(handle)
        os.remove(probe)
        checks["data_dir"] = "ok"
    except OSError:
        logger.exception("Readiness check: the data directory is not writable")
        checks["data_dir"] = "The data directory is not writable."

    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=checks, schema_version=version)
