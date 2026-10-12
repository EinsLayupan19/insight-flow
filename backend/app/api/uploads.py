"""In-memory CSV analysis: check the request, then hand the bytes to the ingestion and analytics modules.

Files sent here are read into memory, analyzed, and discarded. Nothing is saved.
To keep a file and its analysis history, use the dataset endpoints in datasets.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.analytics.insights import SalesInsights, calculate_insights, resolve_insight_columns
from app.analytics.product_performance import (
    ProductPerformance,
    calculate_product_performance,
    resolve_performance_columns,
)
from app.analytics.retail_metrics import ColumnMappingError, RetailMetrics, calculate_retail_metrics, resolve_columns
from app.analytics.sales_trends import DEFAULT_GRAIN, Grain, SalesTrends, calculate_sales_trends, resolve_trend_columns
from app.api.csv_upload import CsvFile, parse_or_422, read_csv_upload
from app.config import Settings, get_settings
from app.ingestion.profiler import QualityReport, profile_csv

router = APIRouter(tags=["uploads"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _column_field(role: str) -> object:
    return Form(description=f"Column to use as {role}. Leave empty to use a column named exactly '{role}', if present.")


class CsvUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    row_count: int
    column_count: int
    columns: list[str]


class CsvProfileResponse(BaseModel):
    filename: str
    size_bytes: int
    profile: QualityReport


class CsvMetricsResponse(BaseModel):
    filename: str
    size_bytes: int
    metrics: RetailMetrics


class CsvTrendsResponse(BaseModel):
    filename: str
    size_bytes: int
    trends: SalesTrends


class CsvPerformanceResponse(BaseModel):
    filename: str
    size_bytes: int
    performance: ProductPerformance


class CsvInsightsResponse(BaseModel):
    filename: str
    size_bytes: int
    insights: SalesInsights


@router.post("/uploads/csv", response_model=CsvUploadResponse)
async def upload_csv(settings: SettingsDep, file: CsvFile = None) -> CsvUploadResponse:
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    return CsvUploadResponse(
        filename=filename,
        size_bytes=len(content),
        row_count=len(parsed.rows),
        column_count=len(parsed.columns),
        columns=parsed.columns,
    )


@router.post("/uploads/csv/profile", response_model=CsvProfileResponse)
async def profile_csv_upload(settings: SettingsDep, file: CsvFile = None) -> CsvProfileResponse:
    """Report missing values, duplicate rows, and column types. The data is never modified."""
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    # Profiling a large file takes seconds of pure CPU work. Running it in a worker
    # thread keeps the server responsive to other requests (like /api/health) meanwhile.
    profile = await run_in_threadpool(profile_csv, parsed)
    return CsvProfileResponse(filename=filename, size_bytes=len(content), profile=profile)


@router.post("/uploads/csv/metrics", response_model=CsvMetricsResponse)
async def csv_metrics(
    settings: SettingsDep,
    file: CsvFile = None,
    order_id_column: Annotated[str | None, _column_field("order_id")] = None,
    quantity_column: Annotated[str | None, _column_field("quantity")] = None,
    unit_price_column: Annotated[str | None, _column_field("unit_price")] = None,
    revenue_column: Annotated[str | None, _column_field("revenue")] = None,
) -> CsvMetricsResponse:
    """Calculate retail metrics with DuckDB. Metrics whose columns are missing are reported as unavailable."""
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    requested = {
        "order_id": order_id_column,
        "quantity": quantity_column,
        "unit_price": unit_price_column,
        "revenue": revenue_column,
    }
    try:
        columns = resolve_columns(parsed.columns, requested)
    except ColumnMappingError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    metrics = await run_in_threadpool(calculate_retail_metrics, parsed, columns)
    return CsvMetricsResponse(filename=filename, size_bytes=len(content), metrics=metrics)


@router.post("/uploads/csv/trends", response_model=CsvTrendsResponse)
async def csv_trends(
    settings: SettingsDep,
    file: CsvFile = None,
    grain: Annotated[Grain, Form(description="Group by day, week (Monday to Sunday), or month.")] = DEFAULT_GRAIN,
    order_date_column: Annotated[str | None, _column_field("order_date")] = None,
    order_id_column: Annotated[str | None, _column_field("order_id")] = None,
    quantity_column: Annotated[str | None, _column_field("quantity")] = None,
    unit_price_column: Annotated[str | None, _column_field("unit_price")] = None,
    revenue_column: Annotated[str | None, _column_field("revenue")] = None,
) -> CsvTrendsResponse:
    """Revenue, orders, and average order value per period, with DuckDB. Rows without a usable date are excluded and counted."""
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    requested = {
        "order_date": order_date_column,
        "order_id": order_id_column,
        "quantity": quantity_column,
        "unit_price": unit_price_column,
        "revenue": revenue_column,
    }
    try:
        columns = resolve_trend_columns(parsed.columns, requested)
    except ColumnMappingError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    trends = await run_in_threadpool(calculate_sales_trends, parsed, columns, grain)
    return CsvTrendsResponse(filename=filename, size_bytes=len(content), trends=trends)


@router.post("/uploads/csv/performance", response_model=CsvPerformanceResponse)
async def csv_performance(
    settings: SettingsDep,
    file: CsvFile = None,
    product_column: Annotated[str | None, _column_field("product")] = None,
    category_column: Annotated[str | None, _column_field("category")] = None,
    order_id_column: Annotated[str | None, _column_field("order_id")] = None,
    quantity_column: Annotated[str | None, _column_field("quantity")] = None,
    unit_price_column: Annotated[str | None, _column_field("unit_price")] = None,
    revenue_column: Annotated[str | None, _column_field("revenue")] = None,
) -> CsvPerformanceResponse:
    """Revenue, quantity, and orders by product and by category. A missing column makes only its breakdown unavailable."""
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    requested = {
        "product": product_column,
        "category": category_column,
        "order_id": order_id_column,
        "quantity": quantity_column,
        "unit_price": unit_price_column,
        "revenue": revenue_column,
    }
    try:
        columns = resolve_performance_columns(parsed.columns, requested)
    except ColumnMappingError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    performance = await run_in_threadpool(calculate_product_performance, parsed, columns)
    return CsvPerformanceResponse(filename=filename, size_bytes=len(content), performance=performance)


@router.post("/uploads/csv/insights", response_model=CsvInsightsResponse)
async def csv_insights(
    settings: SettingsDep,
    file: CsvFile = None,
    grain: Annotated[Grain, Form(description="Compare by day, week (Monday to Sunday), or month.")] = DEFAULT_GRAIN,
    order_date_column: Annotated[str | None, _column_field("order_date")] = None,
    product_column: Annotated[str | None, _column_field("product")] = None,
    category_column: Annotated[str | None, _column_field("category")] = None,
    order_id_column: Annotated[str | None, _column_field("order_id")] = None,
    quantity_column: Annotated[str | None, _column_field("quantity")] = None,
    unit_price_column: Annotated[str | None, _column_field("unit_price")] = None,
    revenue_column: Annotated[str | None, _column_field("revenue")] = None,
) -> CsvInsightsResponse:
    """Plain-English findings from the metrics, trends, and product and category performance. Never states causes."""
    filename, content = await read_csv_upload(file, settings)
    parsed = await run_in_threadpool(parse_or_422, content)  # CPU-bound: keep the event loop free
    requested = {
        "order_date": order_date_column,
        "product": product_column,
        "category": category_column,
        "order_id": order_id_column,
        "quantity": quantity_column,
        "unit_price": unit_price_column,
        "revenue": revenue_column,
    }
    try:
        columns = resolve_insight_columns(parsed.columns, requested)
    except ColumnMappingError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    insights = await run_in_threadpool(calculate_insights, parsed, columns, grain)
    return CsvInsightsResponse(filename=filename, size_bytes=len(content), insights=insights)
