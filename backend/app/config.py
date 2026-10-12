"""Application settings, loaded from environment variables or `backend/.env`.

All configuration lives here so the rest of the code never reads
`os.environ` directly. Secrets use `SecretStr` so they are masked
if a settings object is ever printed or logged.
"""

import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
MEMORY_UNITS = {
    "b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4,
    "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
}
MIN_DUCKDB_MEMORY_BYTES = 64 * 1000**2


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

    # Where saved datasets live: uploaded files in <data_dir>/uploads/ and the SQLite
    # database <data_dir>/insightflow.db. Relative paths are relative to backend/.
    data_dir: Path = BACKEND_DIR / "data"

    # Reserved for a possible later Gemini narrator. Read on the backend only; never sent to the browser.
    gemini_api_key: SecretStr | None = None

    # Optional AI summary of the key findings. "none" (the default) turns it off; the findings work without it.
    # "ollama" uses a model running on this computer through Ollama (free; nothing leaves the machine).
    insights_narrator: Literal["none", "ollama"] = "none"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)

    # Limits for each analysis's DuckDB connection. Without them DuckDB uses every core and about 80% of
    # the machine's memory per connection, and several analyses run at once.
    duckdb_threads: int = Field(default=2, ge=1, le=64)
    duckdb_memory_limit: str = "1GB"

    @field_validator("ollama_url")
    @classmethod
    def _ollama_on_this_computer(cls, value: str) -> str:
        # The narrator is sent sales figures and product names: they must not leave this machine.
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        local = host == "localhost"
        if not local:
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
        if parsed.scheme not in ("http", "https") or not local:
            raise ValueError("OLLAMA_URL must point to Ollama on this computer, such as http://127.0.0.1:11434.")
        return value

    @field_validator("duckdb_memory_limit")
    @classmethod
    def _memory_size(cls, value: str) -> str:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*", value, re.IGNORECASE)
        if not match:
            raise ValueError("DUCKDB_MEMORY_LIMIT must be a size such as 512MB or 1GB.")
        if float(match[1]) * MEMORY_UNITS[match[2].lower()] < MIN_DUCKDB_MEMORY_BYTES:
            raise ValueError("DUCKDB_MEMORY_LIMIT must be at least 64MB; below that, loading even a small file fails.")
        return value.strip()

    @field_validator("data_dir")
    @classmethod
    def _relative_to_backend(cls, value: Path) -> Path:
        # So the location does not depend on the folder the server was started from.
        return value if value.is_absolute() else BACKEND_DIR / value


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance (read once, then cached)."""
    return Settings()
