"""CSV upload routes: check the request, then hand the bytes to the ingestion and analytics modules.

Files are read into memory, analyzed, and discarded. Nothing is saved yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.analytics.retail_metrics import ColumnMappingError, RetailMetrics, calculate_retail_metrics, resolve_columns
from app.config import Settings, get_settings
from app.ingestion.csv_parser import CsvValidationError, ParsedCsv, parse_csv
from app.ingestion.profiler import QualityReport, profile_csv

router = APIRouter(tags=["uploads"])

BYTES_PER_MB = 1024 * 1024

SettingsDep = Annotated[Settings, Depends(get_settings)]
# Optional so a missing file gets our clear 400 message instead of FastAPI's generic 422.
CsvFile = Annotated[UploadFile | None, File(description="A .csv file with a header row.")]


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


@router.post("/uploads/csv", response_model=CsvUploadResponse)
async def upload_csv(settings: SettingsDep, file: CsvFile = None) -> CsvUploadResponse:
    filename, content = await _read_csv_upload(file, settings)
    parsed = _parse_or_422(content)
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
    filename, content = await _read_csv_upload(file, settings)
    parsed = _parse_or_422(content)
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
    filename, content = await _read_csv_upload(file, settings)
    parsed = _parse_or_422(content)
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


async def _read_csv_upload(file: UploadFile | None, settings: Settings) -> tuple[str, bytes]:
    """Check the request (file present, .csv name, size limit) and return the filename and bytes."""
    if file is None or not file.filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No file was uploaded. Send a CSV file in the form field named 'file'.",
        )

    # Check the extension, not the content type: browsers often send Excel's
    # type ("application/vnd.ms-excel") for .csv files on Windows.
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"'{file.filename}' is not a CSV file. Only files ending in .csv are accepted.",
        )

    max_bytes = settings.max_upload_mb * BYTES_PER_MB
    content = await file.read(max_bytes + 1)  # read one extra byte to detect "too large"
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is larger than the {settings.max_upload_mb} MB limit.",
        )
    return file.filename, content


def _parse_or_422(content: bytes) -> ParsedCsv:
    try:
        return parse_csv(content)
    except CsvValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
