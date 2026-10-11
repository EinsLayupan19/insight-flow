"""Shapes of saved datasets and analysis records, as returned by the API."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.retail_metrics import RetailMetrics, Role
from app.ingestion.profiler import QualityReport

AnalysisKind = Literal["profile", "metrics"]


class DatasetSummary(BaseModel):
    id: int
    filename: str = Field(description="Name of the file as uploaded. A label only.")
    size_bytes: int
    row_count: int
    column_count: int
    sha256: str = Field(description="SHA-256 hash of the file content. Identical content is stored once.")
    created_at: datetime = Field(description="When the dataset was saved (UTC).")
    analysis_count: int
    last_analyzed_at: datetime | None


class DatasetDetail(DatasetSummary):
    columns: list[str]
    file_stored: bool = Field(
        description="True if the stored copy of the file is on the server's disk with the expected size."
    )


class DatasetList(BaseModel):
    datasets: list[DatasetSummary]


class SaveDatasetResponse(BaseModel):
    created: bool = Field(
        description="False when a dataset with exactly the same content was already saved. Nothing new was stored."
    )
    dataset: DatasetDetail


class AnalysisRequest(BaseModel):
    kind: AnalysisKind
    column_mapping: dict[Role, str] = Field(
        default_factory=dict,
        description="Metrics only: the column to use for each role. Roles left out use a column with exactly that name.",
    )

    @field_validator("column_mapping")
    @classmethod
    def _drop_blank_choices(cls, mapping: dict[Role, str]) -> dict[Role, str]:
        # A blank choice means "automatic", so it is not stored as a choice.
        return {role: column.strip() for role, column in mapping.items() if column.strip()}

    @model_validator(mode="after")
    def _mapping_only_for_metrics(self) -> "AnalysisRequest":
        if self.kind == "profile" and self.column_mapping:
            raise ValueError("column_mapping only applies to kind 'metrics'.")
        return self


class ProfileHighlights(BaseModel):
    duplicate_row_count: int
    missing_value_count: int
    type_mismatch_count: int


class MetricsHighlights(BaseModel):
    calculated_count: int
    unavailable_count: int


class _AnalysisBase(BaseModel):
    id: int
    dataset_id: int
    created_at: datetime = Field(description="When the analysis ran (UTC).")
    app_version: str = Field(description="InsightFlow version whose rules produced the result.")
    column_mapping: dict[Role, str] = Field(description="Explicit column choices. Empty means automatic matching.")


class AnalysisSummary(_AnalysisBase):
    """One history entry, with a few headline numbers instead of the full result."""

    kind: AnalysisKind
    highlights: ProfileHighlights | MetricsHighlights


class AnalysisList(BaseModel):
    analyses: list[AnalysisSummary]


class ProfileAnalysis(_AnalysisBase):
    kind: Literal["profile"]
    result: QualityReport


class MetricsAnalysis(_AnalysisBase):
    kind: Literal["metrics"]
    result: RetailMetrics


AnalysisRecord = Annotated[ProfileAnalysis | MetricsAnalysis, Field(discriminator="kind")]
