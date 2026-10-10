"""Application settings, loaded from environment variables or `backend/.env`.

All configuration lives here so the rest of the code never reads
`os.environ` directly. Secrets use `SecretStr` so they are masked
if a settings object is ever printed or logged.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `GEMINI_API_KEY=` (blank) becomes None
    )

    app_name: str = "InsightFlow AI"
    app_env: Literal["development", "test", "production"] = "development"

    # Largest CSV upload accepted, in megabytes. Protects the server's memory.
    max_upload_mb: int = Field(default=10, gt=0)

    # Reserved for the AI phase. Read on the backend only; never sent to the browser.
    gemini_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance (read once, then cached)."""
    return Settings()
