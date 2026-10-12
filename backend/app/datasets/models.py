"""Shapes of saved datasets and analysis records, as returned by the API."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.insights import SalesInsights
from app.analytics.product_performance import ProductPerformance
from app.analytics.retail_metrics import RetailMetrics
from app.analytics.sales_trends import DEFAULT_GRAIN, Grain, SalesTrends
from app.ingestion.profiler import QualityReport

AnalysisKind = Literal["profile", "metrics", "trends", "performance", "insights"]
# Every role a column can be mapped to. Some apply to certain kinds only (see KIND_ONLY_ROLES).
MappingRole = Literal["order_date", "product", "category", "order_id", "quantity", "unit_price", "revenue"]
KIND_ONLY_ROLES: dict[str, tuple[AnalysisKind, ...]] = {
    "order_date": ("trends", "insights"),
    "product": ("performance", "insights"),
    "category": ("performance", "insights"),
}
GRAIN_KINDS: tuple[AnalysisKind, ...] = ("trends", "insights")  # kinds that group rows by period


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
    column_mapping: dict[MappingRole, str] = Field(
        default_factory=dict,
        description=(
            "Every kind except profile: the column to use for each role. Roles left out use a column with "
            "exactly that name. order_date applies to trends and insights; product and category to "
            "performance and insights."
        ),
    )
    grain: Grain | None = Field(
        default=None,
        description=f"Trends and insights only: group by day, week (Monday to Sunday), or month. Defaults to {DEFAULT_GRAIN}.",
    )

    @field_validator("column_mapping")
    @classmethod
    def _drop_blank_choices(cls, mapping: dict[MappingRole, str]) -> dict[MappingRole, str]:
        # A blank choice means "automatic", so it is not stored as a choice.
        return {role: column.strip() for role, column in mapping.items() if column.strip()}

    @model_validator(mode="after")
    def _options_match_the_kind(self) -> "AnalysisRequest":
        if self.kind == "profile" and self.column_mapping:
            raise ValueError("column_mapping does not apply to kind 'profile'.")
        for role, kinds in KIND_ONLY_ROLES.items():
            if role in self.column_mapping and self.kind not in kinds:
                allowed = " or ".join(f"'{kind}'" for kind in kinds)
                raise ValueError(f"The column_mapping role '{role}' only applies to kind {allowed}.")
        if self.kind not in GRAIN_KINDS and self.grain is not None:
            raise ValueError("grain only applies to kind 'trends' or 'insights'.")
        if self.kind in GRAIN_KINDS and self.grain is None:
            self.grain = DEFAULT_GRAIN
        return self


class ProfileHighlights(BaseModel):
    duplicate_row_count: int
    missing_value_count: int
    type_mismatch_count: int


class MetricsHighlights(BaseModel):
    calculated_count: int
    unavailable_count: int


class TrendsHighlights(BaseModel):
    grain: Grain
    period_count: int
    calculated_count: int  # of the three series: revenue, order_count, average_order_value
    unavailable_count: int


class PerformanceHighlights(BaseModel):
    product_count: int | None  # None when the product breakdown is unavailable
    category_count: int | None


class InsightsHighlights(BaseModel):
    grain: Grain
    finding_count: int
    high_count: int  # findings of high importance
    not_assessed_count: int  # checks that could not run, each with its reason


class _AnalysisBase(BaseModel):
    id: int
    dataset_id: int
    created_at: datetime = Field(description="When the analysis ran (UTC).")
    app_version: str = Field(description="InsightFlow version whose rules produced the result.")
    column_mapping: dict[MappingRole, str] = Field(description="Explicit column choices. Empty means automatic matching.")


class AnalysisSummary(_AnalysisBase):
    """One history entry, with a few headline numbers instead of the full result."""

    kind: AnalysisKind
    highlights: InsightsHighlights | PerformanceHighlights | TrendsHighlights | MetricsHighlights | ProfileHighlights


class AnalysisList(BaseModel):
    analyses: list[AnalysisSummary]


class ProfileAnalysis(_AnalysisBase):
    kind: Literal["profile"]
    result: QualityReport


class MetricsAnalysis(_AnalysisBase):
    kind: Literal["metrics"]
    result: RetailMetrics


class TrendsAnalysis(_AnalysisBase):
    kind: Literal["trends"]
    grain: Grain
    result: SalesTrends


class PerformanceAnalysis(_AnalysisBase):
    kind: Literal["performance"]
    result: ProductPerformance


class InsightsAnalysis(_AnalysisBase):
    kind: Literal["insights"]
    grain: Grain
    result: SalesInsights


AnalysisRecord = Annotated[
    ProfileAnalysis | MetricsAnalysis | TrendsAnalysis | PerformanceAnalysis | InsightsAnalysis,
    Field(discriminator="kind"),
]
