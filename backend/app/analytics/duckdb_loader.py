"""Load validated CSV rows into an in-memory DuckDB table, exactly as written.

- Every value is stored as text (VARCHAR). Nothing is converted, trimmed, or
  "fixed" on the way in; metric queries convert values themselves.
- Column names from the uploaded file never appear in SQL. Each column gets a
  generated identifier (c0, c1, ...), and `identifiers` maps names to them.
- The database lives in memory and is closed when the `with` block ends.
"""

import csv
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.ingestion.csv_parser import ParsedCsv

TABLE = "uploaded_rows"
LINE_COLUMN = "line"  # the file line number of each row, kept as evidence
_SAFE_IDENTIFIER = re.compile(r"c[0-9]+")


@dataclass(frozen=True)
class LoadedTable:
    connection: duckdb.DuckDBPyConnection
    identifiers: dict[str, str]  # original column name -> generated SQL identifier
    row_count: int

    def identifier(self, column_name: str) -> str:
        """Return the safe SQL identifier for a column name from the file."""
        identifier = self.identifiers[column_name]
        if not _SAFE_IDENTIFIER.fullmatch(identifier):  # defense in depth; we generate these
            raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
        return identifier


@contextmanager
def load_into_duckdb(parsed: ParsedCsv) -> Iterator[LoadedTable]:
    """Load rows into a new in-memory database, yield it, then close it."""
    connection = duckdb.connect(":memory:")
    try:
        identifiers = {name: f"c{index}" for index, name in enumerate(parsed.columns)}
        _create_table(connection, list(identifiers.values()))
        if parsed.rows:
            _bulk_insert(connection, parsed, list(identifiers.values()))
        _check_row_count(connection, expected=len(parsed.rows))
        yield LoadedTable(connection=connection, identifiers=identifiers, row_count=len(parsed.rows))
    finally:
        connection.close()


def _create_table(connection: duckdb.DuckDBPyConnection, column_ids: list[str]) -> None:
    columns_sql = ", ".join([f"{LINE_COLUMN} BIGINT"] + [f"{c} VARCHAR" for c in column_ids])
    connection.execute(f"CREATE TABLE {TABLE} ({columns_sql})")


def _bulk_insert(connection: duckdb.DuckDBPyConnection, parsed: ParsedCsv, column_ids: list[str]) -> None:
    # Inserting row by row from Python is extremely slow (minutes for 100k rows).
    # Instead, write the already-validated rows to a temporary CSV in a fixed format
    # we control (every value quoted), and let DuckDB's native reader bulk-load it.
    names = [LINE_COLUMN, *column_ids]
    with tempfile.TemporaryDirectory(prefix="insightflow-") as temp_dir:
        path = Path(temp_dir) / "rows.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writerows([row.line, *row.values] for row in parsed.rows)

        relation = connection.read_csv(
            str(path),
            header=False,
            sep=",",
            quotechar='"',
            escapechar='"',
            names=names,
            dtype={name: "BIGINT" if name == LINE_COLUMN else "VARCHAR" for name in names},
            auto_detect=False,
            allow_quoted_nulls=False,  # keep "" as an empty string, not NULL
            strict_mode=True,
            encoding="utf-8",
        )
        relation.insert_into(TABLE)  # copies the data, so the temp file can be deleted


def _check_row_count(connection: duckdb.DuckDBPyConnection, expected: int) -> None:
    loaded = connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    if loaded != expected:
        raise RuntimeError(f"DuckDB loaded {loaded} rows, but the file has {expected}. No metrics were calculated.")
