"""Load validated CSV rows into an in-memory DuckDB table, exactly as written.

- Every value is stored as text (VARCHAR). Nothing is converted, trimmed, or
  "fixed" on the way in; metric queries convert values themselves.
- Column names from the uploaded file never appear in SQL. Each column gets a
  generated identifier (c0, c1, ...), and `identifiers` maps names to them.
- The database lives in memory and is closed when the `with` block ends. It uses the
  configured thread and memory limits, and anything it spills to disk goes into the
  request's own temporary directory, which is removed at the end (never the working
  directory, DuckDB's default).
"""

import csv
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.config import get_settings
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
    """Load rows into a new in-memory database, yield it, then close it and remove its temporary files."""
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="insightflow-") as work_dir:
        spill = Path(work_dir) / "spill"
        spill.mkdir()
        connection = duckdb.connect(
            ":memory:",
            config={
                "threads": settings.duckdb_threads,
                "memory_limit": settings.duckdb_memory_limit,
                "temp_directory": str(spill),
            },
        )
        try:
            connection.execute("SET enable_progress_bar = false")  # it would print to the server's output
            identifiers = {name: f"c{index}" for index, name in enumerate(parsed.columns)}
            _create_table(connection, list(identifiers.values()))
            if parsed.rows:
                _bulk_insert(connection, parsed, list(identifiers.values()), Path(work_dir))
            _check_row_count(connection, expected=len(parsed.rows))
            yield LoadedTable(connection=connection, identifiers=identifiers, row_count=len(parsed.rows))
        finally:
            connection.close()


def _create_table(connection: duckdb.DuckDBPyConnection, column_ids: list[str]) -> None:
    columns_sql = ", ".join([f"{LINE_COLUMN} BIGINT"] + [f"{c} VARCHAR" for c in column_ids])
    connection.execute(f"CREATE TABLE {TABLE} ({columns_sql})")


def _bulk_insert(connection: duckdb.DuckDBPyConnection, parsed: ParsedCsv, column_ids: list[str], work_dir: Path) -> None:
    # Inserting row by row from Python is extremely slow (minutes for 100k rows).
    # Instead, write the already-validated rows to a temporary CSV in a fixed format
    # we control (every value quoted), and let DuckDB's native reader bulk-load it.
    # The file lives in the request's temporary directory and is removed with it.
    names = [LINE_COLUMN, *column_ids]
    path = work_dir / "rows.csv"
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
    relation.insert_into(TABLE)  # copies the data into DuckDB
    path.unlink()  # the copy is no longer needed; free the disk space now


def _check_row_count(connection: duckdb.DuckDBPyConnection, expected: int) -> None:
    loaded = connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    if loaded != expected:
        raise RuntimeError(f"DuckDB loaded {loaded} rows, but the file has {expected}. No metrics were calculated.")
