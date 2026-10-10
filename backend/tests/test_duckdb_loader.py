"""Tests for loading parsed CSV rows into DuckDB without changing any value."""

import duckdb
import pytest

from app.analytics.duckdb_loader import LINE_COLUMN, TABLE, load_into_duckdb
from app.ingestion.csv_parser import CsvRow, ParsedCsv


def stored_rows(table) -> list[tuple]:
    return table.connection.execute(f"SELECT * FROM {TABLE} ORDER BY {LINE_COLUMN}").fetchall()


def test_values_are_stored_exactly_as_text() -> None:
    tricky = ["", "  ", " 12 ", "N/A", "NULL", "\\N", 'say "hi", ok', "two\nlines", "café ✓", "0012"]
    parsed = ParsedCsv(columns=["value"], rows=[CsvRow(line=i + 2, values=[v]) for i, v in enumerate(tricky)])

    with load_into_duckdb(parsed) as table:
        assert [row[1] for row in stored_rows(table)] == tricky
        types = table.connection.execute(f"SELECT column_name, column_type FROM (DESCRIBE {TABLE})").fetchall()

    assert types == [("line", "BIGINT"), ("c0", "VARCHAR")]


def test_file_line_numbers_are_kept_as_evidence() -> None:
    parsed = ParsedCsv(columns=["a"], rows=[CsvRow(line=2, values=["x"]), CsvRow(line=5, values=["y"])])

    with load_into_duckdb(parsed) as table:
        assert stored_rows(table) == [(2, "x"), (5, "y")]


def test_column_names_never_become_sql_identifiers() -> None:
    hostile = ['quantity"; DROP TABLE uploaded_rows; --', "select", "a b", "ünï"]
    parsed = ParsedCsv(columns=hostile, rows=[CsvRow(line=2, values=["1", "2", "3", "4"])])

    with load_into_duckdb(parsed) as table:
        assert table.identifiers == {hostile[0]: "c0", "select": "c1", "a b": "c2", "ünï": "c3"}
        assert stored_rows(table) == [(2, "1", "2", "3", "4")]


def test_zero_rows_still_creates_the_table() -> None:
    with load_into_duckdb(ParsedCsv(columns=["a", "b"], rows=[])) as table:
        assert table.row_count == 0
        assert stored_rows(table) == []


def test_connection_is_closed_after_use() -> None:
    with load_into_duckdb(ParsedCsv(columns=["a"], rows=[CsvRow(line=2, values=["x"])])) as table:
        connection = table.connection

    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")
