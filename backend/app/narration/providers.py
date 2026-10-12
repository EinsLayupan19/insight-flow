"""The narrator interface. Ollama (local) is the only provider today; others can implement the same protocol."""

from typing import Protocol

from pydantic import BaseModel

from app.config import Settings

NOT_CONFIGURED = (
    "No narrator is configured. To write AI summaries with a free local model, install Ollama, "
    "set INSIGHTS_NARRATOR=ollama in backend/.env, and restart the backend."
)


class NarratorError(Exception):
    """The narrator could not answer. The message is shown to users and never contains secrets."""


class NarratorStatus(BaseModel):
    enabled: bool  # a narrator is configured
    provider: str | None
    model: str | None
    available: bool  # it answered a status check just now
    reason: str | None  # why it is unavailable, with the fix when there is one


class Narrator(Protocol):
    provider: str
    model: str

    def status(self) -> NarratorStatus: ...

    def write(self, system: str, prompt: str) -> str:
        """Return the model's text, or raise NarratorError."""
        ...


def disabled_status() -> NarratorStatus:
    return NarratorStatus(enabled=False, provider=None, model=None, available=False, reason=NOT_CONFIGURED)


def get_narrator(settings: Settings) -> Narrator | None:
    """The configured narrator, or None when narration is off (the default)."""
    if settings.insights_narrator == "ollama":
        from app.narration.ollama import OllamaNarrator

        return OllamaNarrator(settings.ollama_url, settings.ollama_model, settings.ollama_timeout_seconds)
    return None
