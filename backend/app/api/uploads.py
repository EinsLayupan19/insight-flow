"""CSV upload: checks the request, then hands the bytes to the ingestion module.

The file is read into memory, summarized, and discarded. Nothing is saved yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.ingestion.csv_parser import CsvValidationError, summarize_csv

router = APIRouter(tags=["uploads"])

BYTES_PER_MB = 1024 * 1024


class CsvUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    row_count: int
    column_count: int
    columns: list[str]


@router.post("/uploads/csv", response_model=CsvUploadResponse)
async def upload_csv(
    settings: Annotated[Settings, Depends(get_settings)],
    # Optional here so a missing file gets our clear 400 message instead of FastAPI's generic 422.
    file: Annotated[UploadFile | None, File(description="A .csv file with a header row.")] = None,
) -> CsvUploadResponse:
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

    try:
        summary = summarize_csv(content)
    except CsvValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    return CsvUploadResponse(
        filename=file.filename,
        size_bytes=len(content),
        row_count=summary.row_count,
        column_count=len(summary.columns),
        columns=summary.columns,
    )
