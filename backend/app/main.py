"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app import __version__
from app.api import datasets, health, narration, uploads

API_PREFIX = "/api"


def create_app() -> FastAPI:
    app = FastAPI(title="InsightFlow AI API", version=__version__)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(datasets.router, prefix=API_PREFIX)
    app.include_router(narration.router, prefix=API_PREFIX)
    return app


app = create_app()
