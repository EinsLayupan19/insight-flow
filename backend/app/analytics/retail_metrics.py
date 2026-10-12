"""Basic retail metrics calculated with DuckDB, only when the needed columns exist.

Columns are matched by exact name (`order_id`, `quantity`, `unit_price`,
`revenue`) unless the caller names a different column for a role. Nothing is
guessed: if a metric's columns are missing, it is reported as "unavailable"
with a reason. Values that are blank or not plain numbers are excluded from a
metric and counted, never silently treated as zero.

SQL safety: queries only contain generated identifiers (c0, c1, ...) from the
loader. Values and patterns are passed as query parameters.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeVar

import duckdb
from pydantic import BaseModel

from app.analytics.duckdb_loader import LINE_COLUMN, TABLE, LoadedTable, load_into_duckdb
from app.analytics.evidence import lines_suffix
from app.ingestion.csv_parser import ParsedCsv

Role = Literal["order_id", "quantity", "unit_price", "revenue"]
ROLES: tuple[Role, ...] = ("order_id", "quantity", "unit_price", "revenue")
R = TypeVar("R", bound=str)

# Optional sign, digits, optional decimal point with at most 8 decimal places.
# No currency symbols, thousands separators, or scientific notation.
NUMBER_PATTERN = r"[+-]?(?:[0-9]+(?:\.[0-9]{0,8})?|\.[0-9]{1,8})"
DECIMAL_TYPE = "DECIMAL(38, 8)"  # exact decimal math (0.1 + 0.2 == 0.3), unlike floating point

NUMBER_RULE = (
    "A usable number is plain text like 42, -3, or 18.50: an optional sign, digits, and at most "
    "8 decimal places. Surrounding spaces are ignored. Currency symbols ($5), thousands "
    "separators (1,000), and scientific notation (1e3) are not accepted. Values that are blank "
    "or not usable numbers are excluded from a metric and counted in rows_excluded."
)


class ColumnMappingError(ValueError):
    """A requested column does not exist or is used twice. The message is shown to the user."""


class MetricResult(BaseModel):
    status: Literal["calculated", "unavailable"]
    value: int | float | None
    definition: str
    columns_used: list[str]
    rows_included: int | None
    rows_excluded: int | None
    notes: list[str]


class RetailMetrics(BaseModel):
    columns_used: dict[Role, str | None]
    number_rule: str
    row_count: MetricResult
    total_quantity: MetricResult
    total_revenue: MetricResult
    order_count: MetricResult
    average_order_value: MetricResult


# ---------- Column mapping ----------


def resolve_columns(
    available: list[str], requested: Mapping[R, str | None], roles: Sequence[R] = ROLES
) -> dict[R, str | None]:
    """Pick the column for each role: the requested name, else an exact-name match, else None."""
    resolved: dict[R, str | None] = {}
    for role in roles:
        chosen = (requested.get(role) or "").strip() or None
        if chosen is not None and chosen not in available:
            raise ColumnMappingError(
                f"{role}_column is '{chosen}', but the file has no column with that exact name. "
                f"Available columns: {', '.join(available)}."
            )
        resolved[role] = chosen if chosen is not None else (role if role in available else None)

    used = [name for name in resolved.values() if name is not None]
    repeated = sorted({name for name in used if used.count(name) > 1})
    if repeated:
        raise ColumnMappingError(f"Column '{repeated[0]}' is assigned to more than one role. Each role needs its own column.")
    return resolved


# ---------- Metrics ----------


def calculate_retail_metrics(parsed: ParsedCsv, columns: dict[Role, str | None]) -> RetailMetrics:
    """Load the rows into DuckDB and calculate every metric the available columns support."""
    with load_into_duckdb(parsed) as table:
        revenue = _total_revenue(table, columns)
        return RetailMetrics(
            columns_used=columns,
            number_rule=NUMBER_RULE,
            row_count=_row_count(table),
            total_quantity=_total_quantity(table, columns),
            total_revenue=revenue,
            order_count=_order_count(table, columns),
            average_order_value=_average_order_value(table, columns, revenue),
        )


def _row_count(table: LoadedTable) -> MetricResult:
    all_columns = ", ".join(table.identifier(name) for name in table.identifiers)
    distinct = table.connection.execute(f"SELECT count(*) FROM (SELECT DISTINCT {all_columns} FROM {TABLE})").fetchone()[0]
    duplicates = table.row_count - distinct
    notes = (
        [f"{duplicates} exact duplicate row(s) are included in every metric as-is. Review them with the profile endpoint."]
        if duplicates
        else []
    )
    return MetricResult(
        status="calculated",
        value=table.row_count,
        definition="Number of data rows. The header and blank lines are not counted. Duplicate rows are counted as-is.",
        columns_used=[],
        rows_included=table.row_count,
        rows_excluded=0,
        notes=notes,
    )


def _total_quantity(table: LoadedTable, columns: dict[Role, str | None]) -> MetricResult:
    definition = "Sum of the quantity column. Negative quantities (for example returns) are included as-is."
    quantity = columns["quantity"]
    if quantity is None:
        return _unavailable(definition, "No column named 'quantity'. To use another column, send quantity_column.")
    return _sum_metric(table, number_sql(table, quantity), [quantity], definition)


@dataclass(frozen=True)
class RevenueSource:
    """Which columns per-row revenue comes from, and what that revenue means."""

    definition: str
    columns_used: list[str]


REVENUE_FALLBACK_DEFINITION = "Sum of a revenue column, or of quantity x unit_price per row."


def revenue_source(columns: Mapping[str, str | None]) -> RevenueSource | None:
    """The revenue column if present, else quantity x unit_price, else None (see revenue_unavailable_reason)."""
    revenue, quantity, unit_price = columns["revenue"], columns["quantity"], columns["unit_price"]
    if revenue is not None:
        return RevenueSource(
            f"Sum of the '{revenue}' column as recorded in the file. Whether it already includes "
            "discounts, returns, or refunds depends on how the file was produced.",
            [revenue],
        )
    if quantity is not None and unit_price is not None:
        return RevenueSource(
            "Sum of quantity x unit_price for each row: gross sales before any discounts, "
            "returns, or refunds are taken into account.",
            [quantity, unit_price],
        )
    return None


def revenue_unavailable_reason(columns: Mapping[str, str | None]) -> str:
    missing = [name for name in ("quantity", "unit_price") if columns[name] is None]
    return (
        f"Needs a 'revenue' column, or both 'quantity' and 'unit_price'. Missing: {', '.join(missing)}. "
        "To use other columns, send revenue_column, or quantity_column and unit_price_column."
    )


def _total_revenue(table: LoadedTable, columns: dict[Role, str | None]) -> MetricResult:
    source = revenue_source(columns)
    if source is None:
        return _unavailable(REVENUE_FALLBACK_DEFINITION, revenue_unavailable_reason(columns))
    return _sum_metric(table, revenue_value_sql(table, columns), source.columns_used, source.definition)


def _order_count(table: LoadedTable, columns: dict[Role, str | None]) -> MetricResult:
    definition = "Number of distinct order IDs (exact text match). Rows with a blank order ID are excluded."
    order_id = columns["order_id"]
    if order_id is None:
        return _unavailable(definition, "No column named 'order_id'. To use another column, send order_id_column.")

    oid = table.identifier(order_id)
    orders, included = table.connection.execute(
        f"SELECT COUNT(DISTINCT {oid}), COUNT(*) FROM {TABLE} WHERE trim({oid}) <> ''"
    ).fetchone()
    excluded = table.row_count - included
    blank_id_sql = f"trim({oid}) = ''"
    notes = [f"{excluded} row(s) have a blank order ID{_lines_suffix(table, blank_id_sql, excluded)}."] if excluded else []
    if included == 0:
        return _unavailable(definition, "Every order ID is blank.", [order_id])
    return MetricResult(
        status="calculated", value=orders, definition=definition, columns_used=[order_id],
        rows_included=included, rows_excluded=excluded, notes=notes,
    )


def _average_order_value(
    table: LoadedTable, columns: dict[Role, str | None], revenue: MetricResult
) -> MetricResult:
    definition = (
        "Total revenue / number of distinct orders, using only rows that have both an order ID "
        "and a usable revenue value. Uses the same revenue definition as total_revenue."
    )
    order_id = columns["order_id"]
    if order_id is None:
        return _unavailable(
            definition,
            "Needs an order ID column, because one order can span several rows. "
            "No column named 'order_id'; to use another column, send order_id_column.",
        )
    if revenue.status != "calculated":
        return _unavailable(definition, "Total revenue could not be calculated, so neither can this.")

    oid = table.identifier(order_id)
    value_sql = revenue_value_sql(table, columns)
    try:
        total, orders, included = table.connection.execute(
            f"SELECT SUM(v), COUNT(DISTINCT oid), COUNT(*) FROM "
            f"(SELECT {oid} AS oid, {value_sql} AS v FROM {TABLE}) WHERE v IS NOT NULL AND trim(oid) <> ''",
            {"number_pattern": NUMBER_PATTERN},
        ).fetchone()
    except duckdb.OutOfRangeException:
        return _unavailable(definition, "The values are too large to total exactly.", [order_id, *revenue.columns_used])

    used = [order_id, *revenue.columns_used]
    if orders == 0:
        return _unavailable(definition, "No rows have both an order ID and a usable revenue value.", used)
    excluded = table.row_count - included
    notes = [f"{excluded} row(s) excluded because the order ID was blank or revenue was not usable."] if excluded else []
    return MetricResult(
        status="calculated", value=float(Decimal(total) / orders), definition=definition,
        columns_used=used, rows_included=included, rows_excluded=excluded, notes=notes,
    )


# ---------- Helpers ----------


def _sum_metric(table: LoadedTable, value_sql: str, columns_used: list[str], definition: str) -> MetricResult:
    """Sum a numeric SQL expression, counting excluded and negative rows."""
    try:
        total, included, negatives = table.connection.execute(
            f"SELECT SUM(v), COUNT(v), COUNT(*) FILTER (WHERE v < 0) FROM (SELECT {value_sql} AS v FROM {TABLE})",
            {"number_pattern": NUMBER_PATTERN},
        ).fetchone()
    except duckdb.OutOfRangeException:
        return _unavailable(definition, "The values are too large to total exactly.", columns_used)

    names = " or ".join(f"'{name}'" for name in columns_used)
    if included == 0:
        return _unavailable(definition, f"No row has a usable number in {names}.", columns_used)

    excluded = table.row_count - included
    notes: list[str] = []
    if excluded:
        lines = _lines_suffix(table, f"({value_sql}) IS NULL", excluded)
        notes.append(f"{excluded} row(s) excluded because {names} was blank or not a usable number{lines}.")
    if negatives:
        notes.append(f"{negatives} row(s) have negative values (possibly returns or refunds); they are included as-is.")
    return MetricResult(
        status="calculated", value=float(total), definition=definition, columns_used=columns_used,
        rows_included=included, rows_excluded=excluded, notes=notes,
    )


def revenue_value_sql(table: LoadedTable, columns: Mapping[str, str | None]) -> str:
    """Per-row revenue: the revenue column if present, otherwise quantity x unit_price."""
    revenue, quantity, unit_price = columns["revenue"], columns["quantity"], columns["unit_price"]
    if revenue is not None:
        return number_sql(table, revenue)
    assert quantity is not None and unit_price is not None  # callers check availability first
    return f"({number_sql(table, quantity)}) * ({number_sql(table, unit_price)})"


def number_sql(table: LoadedTable, column_name: str) -> str:
    """SQL that turns a text column into an exact decimal, or NULL if it isn't a usable number."""
    c = table.identifier(column_name)
    return f"CASE WHEN regexp_full_match(trim({c}), $number_pattern) THEN TRY_CAST(trim({c}) AS {DECIMAL_TYPE}) END"


def _lines_suffix(table: LoadedTable, condition_sql: str, total: int) -> str:
    """Return ' (lines 4, 7, ...)' listing the first rows that match a condition, as evidence."""
    params = {"number_pattern": NUMBER_PATTERN} if "$number_pattern" in condition_sql else {}
    return lines_suffix(table.connection, TABLE, condition_sql, total, params, LINE_COLUMN)


def _unavailable(definition: str, reason: str, columns_used: list[str] | None = None) -> MetricResult:
    return MetricResult(
        status="unavailable", value=None, definition=definition, columns_used=columns_used or [],
        rows_included=None, rows_excluded=None, notes=[reason],
    )
