"""Unit tests for the CSV parser: no HTTP, just bytes in and summary/error out."""

import pytest

from app.ingestion.csv_parser import CsvValidationError, summarize_csv


def test_valid_csv_returns_row_count_and_columns() -> None:
    summary = summarize_csv(b"store,revenue\nNorth,100\nSouth,250\n")

    assert summary.row_count == 2
    assert summary.columns == ["store", "revenue"]


def test_quoted_values_with_commas_are_one_field() -> None:
    summary = summarize_csv(b'product,price\n"Coffee Beans, 1kg",18.50\n')

    assert summary.row_count == 1
    assert summary.columns == ["product", "price"]


def test_excel_utf8_bom_is_removed_from_first_column() -> None:
    summary = summarize_csv("﻿store,revenue\nNorth,100\n".encode("utf-8"))

    assert summary.columns == ["store", "revenue"]


def test_windows_line_endings_and_blank_lines_are_handled() -> None:
    summary = summarize_csv(b"store,revenue\r\nNorth,100\r\n\r\nSouth,250\r\n")

    assert summary.row_count == 2


def test_header_whitespace_is_trimmed() -> None:
    summary = summarize_csv(b" store , revenue \nNorth,100\n")

    assert summary.columns == ["store", "revenue"]


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (b"", "empty"),
        (b"   \n\n", "empty"),
        (b"store,revenue\n", "no data rows"),
        (b"store,revenue\nNorth,100\nSouth\n", "Line 3 has 1 values, but the header has 2 columns"),
        (b"store,revenue\nNorth,100,extra\n", "Line 2 has 3 values"),
        (b"store,store\nNorth,South\n", "Duplicate column names: store"),
        (b"store,,revenue\nNorth,x,100\n", "Column 2 has no header name"),
        ("store,revenue\nCafé,100\n".encode("cp1252"), "not UTF-8"),
        (b"store,revenue\nNor\x00th,100\n", "binary data"),
        ("store,revenue\nNorth,100\n".encode("utf-16-le"), "binary data"),
        (b"notes\n" + b"x" * 200_000 + b"\n", "Could not parse the CSV near line 2"),
    ],
    ids=[
        "empty-file",
        "whitespace-only",
        "header-only",
        "row-too-short",
        "row-too-long",
        "duplicate-columns",
        "blank-column-name",
        "not-utf8",
        "null-byte",
        "utf16-without-bom",
        "field-over-csv-limit",
    ],
)
def test_invalid_csv_raises_clear_error(content: bytes, expected_message: str) -> None:
    with pytest.raises(CsvValidationError, match=expected_message):
        summarize_csv(content)
