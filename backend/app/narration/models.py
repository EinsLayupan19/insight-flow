"""Shapes of recorded narrations, as returned by the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NarrationStatus = Literal["accepted", "rejected", "failed"]


class NarrationRecord(BaseModel):
    id: int
    dataset_id: int
    analysis_id: int = Field(description="The insights analysis that was summarized.")
    created_at: datetime
    provider: str
    model: str
    prompt_version: str
    status: NarrationStatus = Field(
        description="accepted: the model's text passed every check. rejected: it failed a check. failed: the model did not answer."
    )
    source: Literal["ai", "template"] = Field(description="Whether text was written by the model or is the template summary.")
    text: str = Field(description="What to show. The model's text only when status is accepted.")
    problems: list[str] = Field(description="Why the model's text was not used, when it was not.")


class NarrationList(BaseModel):
    narrations: list[NarrationRecord]
