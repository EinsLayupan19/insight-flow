"""CSV upload routes: check the request, then hand the bytes to the ingestion modules.

Files are read into memory, analyzed, and discarded. Nothing is saved yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.ingestion.csv_parser import CsvValidationError, ParsedCsv, parse_csv
from app.ingestion.profiler import QualityReport, profile_csv

router = APIRouter(tags=["uploads"])

BYTES_PER_MB = 1024 * 1024

SettingsDep = Annotated[Settings, Depends(get_settings)]
# Optional so a missing file gets our clear 400 message instead of FastAPI's generic 422.
CsvFile = Annotated[UploadFile | None, File(description="A .csv file with a header row.")]


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
