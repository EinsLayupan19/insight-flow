"""Request checks shared by every endpoint that accepts a CSV upload.

The same rules apply whether a file is analyzed in memory (uploads.py) or saved
to the dataset library (datasets.py): a file in the form field "file", a name
ending in .csv, a size limit, and content the CSV parser accepts.
"""

from typing import Annotated

from fastapi import File, HTTPException, UploadFile, status

from app.config import Settings
from app.ingestion.csv_parser import CsvValidationError, ParsedCsv, parse_csv

BYTES_PER_MB = 1024 * 1024

# Optional so a missing file gets our clear 400 message instead of FastAPI's generic 422.
CsvFile = Annotated[UploadFile | None, File(description="A .csv file with a header row.")]


async def read_csv_upload(file: UploadFile | None, settings: Settings) -> tuple[str, bytes]:
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


def parse_or_422(content: bytes) -> ParsedCsv:
    try:
        return parse_csv(content)
    except CsvValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
