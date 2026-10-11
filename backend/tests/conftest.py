"""Shared fixtures. Tests that save datasets use a temporary data directory, never backend/data."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def library_client(data_dir: Path) -> TestClient:
    """An API client whose dataset library lives in a temporary directory."""
    settings = Settings(data_dir=data_dir, _env_file=None)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)
