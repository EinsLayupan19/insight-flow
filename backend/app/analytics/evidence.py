"""Evidence for notes: the file lines of the first rows that match a condition.

Shared by every analysis that excludes or flags rows, so each note points to the same
kind of proof: " (lines 4, 7, 9, ...)". Conditions are built from generated identifiers
only; values are passed as query parameters.
"""

from collections.abc import Mapping

import duckdb

MAX_LINE_EXAMPLES = 5


def lines_suffix(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    condition_sql: str,
    total: int,
    params: Mapping[str, object] | None = None,
    line_column: str = "line",
) -> str:
    """Return ' (lines 4, 7, ...)' for up to 5 matching rows, with '...' when more match."""
    sql = f"SELECT {line_column} FROM {table} WHERE {condition_sql} ORDER BY {line_column} LIMIT {MAX_LINE_EXAMPLES}"
    lines = [str(row[0]) for row in connection.execute(sql, dict(params or {})).fetchall()]
    more = ", ..." if total > len(lines) else ""
    return f" (lines {', '.join(lines)}{more})" if lines else ""
