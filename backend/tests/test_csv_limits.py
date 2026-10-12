"""Header limits: at most 1,000 columns, and duplicate names found in linear time (audit F2, F16)."""

import time

import pytest

from app.ingestion.csv_parser import MAX_COLUMNS, CsvValidationError, duplicate_names, parse_csv


def csv_with_columns(count: int) -> bytes:
    header = ",".join(f"c{i}" for i in range(count))
    row = ",".join("1" for _ in range(count))
    return f"{header}\n{row}\n".encode()


def test_the_column_limit_is_1000() -> None:
    assert MAX_COLUMNS == 1000


def test_exactly_1000_columns_are_accepted() -> None:
    parsed = parse_csv(csv_with_columns(1000))

    assert len(parsed.columns) == 1000
    assert len(parsed.rows) == 1


def test_1001_columns_are_rejected_with_a_clear_message() -> None:
    with pytest.raises(CsvValidationError) as error:
        parse_csv(csv_with_columns(1001))

    assert str(error.value) == "The file has 1,001 columns. InsightFlow accepts at most 1,000 columns."


def test_a_very_wide_header_is_rejected_quickly() -> None:
    header = ",".join(f"c{i}" for i in range(200_000)).encode()  # about 1.3 MB of column names

    start = time.perf_counter()
    with pytest.raises(CsvValidationError, match="200,000 columns"):
        parse_csv(header + b"\n" + b"1\n")
    assert time.perf_counter() - start < 2.0


def test_duplicate_detection_takes_linear_time() -> None:
    names = [f"c{i}" for i in range(200_000)] + ["c7", "c5", "c7"]

    start = time.perf_counter()
    found = duplicate_names(names)

    assert found == ["c5", "c7"]
    assert time.perf_counter() - start < 1.0  # the quadratic version took hours at this size


def test_duplicate_column_messages_are_unchanged() -> None:
    with pytest.raises(CsvValidationError) as error:
        parse_csv(b"b,a,b,a,c\n1,2,3,4,5\n")

    assert str(error.value) == "Duplicate column names: a, b. Each column name must be unique."


def test_the_column_limit_is_checked_before_duplicates() -> None:
    header = ",".join(["same"] * 1001).encode()

    with pytest.raises(CsvValidationError, match="1,001 columns"):
        parse_csv(header + b"\n" + b",".join([b"1"] * 1001) + b"\n")
