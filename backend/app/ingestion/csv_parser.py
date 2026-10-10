"""Parse raw CSV bytes and describe their shape (row count, column names).

This module is deliberately strict: if the file is ambiguous (duplicate or
blank column names, rows with the wrong number of values), it raises an
error instead of guessing. Silent fixes would make later analysis untrustworthy.
"""

import csv
import io
from _csv import Reader as CsvReader  # the type that csv.reader() returns
from dataclasses import dataclass


class CsvValidationError(ValueError):
    """The file could not be read as a usable CSV. The message is shown to the user."""


@dataclass(frozen=True)
class CsvSummary:
    row_count: int
    columns: list[str]


def summarize_csv(content: bytes) -> CsvSummary:
    """Validate CSV bytes and return their row count and column names."""
    text = _decode(content)
    if not text.strip():
        raise CsvValidationError("The file is empty.")

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        columns = _read_header(reader)
        row_count = _count_rows(reader, expected_width=len(columns))
    except csv.Error as error:
        raise CsvValidationError(f"Could not parse the CSV near line {reader.line_num}: {error}.") from error

    if row_count == 0:
        raise CsvValidationError("The file has column headers but no data rows.")
    return CsvSummary(row_count=row_count, columns=columns)


def _decode(content: bytes) -> str:
    # Python's csv module accepts NUL bytes, but real CSV text never contains them.
    if b"\x00" in content:
        raise CsvValidationError(
            "The file contains binary data. It may be another file type renamed to .csv, "
            "or saved as UTF-16. Save it as 'CSV UTF-8' and try again."
        )
    # "utf-8-sig" also removes the invisible BOM that Excel adds to "CSV UTF-8" files.
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvValidationError(
            "The file is not UTF-8 text. If it came from Excel, use "
            "File > Save As > 'CSV UTF-8 (Comma delimited)'."
        ) from error


def _read_header(reader: CsvReader) -> list[str]:
    header = next(reader, None)
    while header == []:  # skip blank lines before the header
        header = next(reader, None)
    if header is None:
        raise CsvValidationError("The file is empty.")

    columns = [name.strip() for name in header]
    for position, name in enumerate(columns, start=1):
        if not name:
            raise CsvValidationError(f"Column {position} has no header name. Every column needs a name.")

    duplicates = sorted({name for name in columns if columns.count(name) > 1})
    if duplicates:
        raise CsvValidationError(f"Duplicate column names: {', '.join(duplicates)}. Each column name must be unique.")
    return columns


def _count_rows(reader: CsvReader, expected_width: int) -> int:
    row_count = 0
    for row in reader:
        if not row:  # blank line
            continue
        if len(row) != expected_width:
            raise CsvValidationError(
                f"Line {reader.line_num} has {len(row)} values, but the header has {expected_width} columns."
            )
        row_count += 1
    return row_count
