"""Sales trends calculated with DuckDB: revenue, orders, and average order value per day, week, or month.

The rules are the retail metrics' rules, applied per period:
- Columns are matched by exact name (`order_date`, plus the metrics' `order_id`,
  `quantity`, `unit_price`, `revenue`) unless the caller names another column.
- Revenue per row is the same value total_revenue uses, with the same number rule.
- A usable date follows the data-quality check's date rule: a real calendar date
  written YYYY-MM-DD. Rows without one are excluded from every trend and counted,
  with line numbers, never guessed.
- Periods between the first and last date that have no rows are listed with no
  values (null, never zero), so gaps stay visible.

SQL safety: queries only contain generated identifiers (c0, c1, ...) from the
loader. Values and patterns are passed as query parameters.
"""

import calendar
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import duckdb
from pydantic import BaseModel

from app.analytics.duckdb_loader import LINE_COLUMN, TABLE, LoadedTable, load_into_duckdb
from app.analytics.evidence import lines_suffix
from app.analytics.retail_metrics import (
    NUMBER_PATTERN,
    NUMBER_RULE,
    REVENUE_FALLBACK_DEFINITION,
    ROLES,
    MetricResult,
    Role,
    resolve_columns,
    revenue_source,
    revenue_unavailable_reason,
    revenue_value_sql,
)
from app.ingestion.csv_parser import ParsedCsv
from app.ingestion.profiler import DATE_PATTERN

Grain = Literal["day", "week", "month"]
GRAINS: tuple[Grain, ...] = ("day", "week", "month")
DEFAULT_GRAIN: Grain = "month"

TrendRole = Literal["order_date", "order_id", "quantity", "unit_price", "revenue"]
TREND_ROLES: tuple[TrendRole, ...] = ("order_date", *ROLES)

# Enough for about 5 years of daily periods. A wider range usually means a mistyped
# year, and the response stays small enough to chart and read.
MAX_PERIODS = 2000
ROWS = "trend_rows"  # working table: one row per uploaded row, with its date, period, revenue, and order ID

DATE_RULE = (
    "A usable date is a real calendar date written YYYY-MM-DD, such as 2026-01-05 (the same rule as "
    "the data-quality check). Surrounding spaces are ignored. Other formats (05/01/2026), dates with a "
    "time (2026-01-05 10:00), and impossible dates (2026-02-30) are not accepted. Rows without a usable "
    "date are excluded from every trend and counted in rows_excluded."
)

GRAIN_NAMES: dict[Grain, str] = {"day": "day", "week": "week (Monday to Sunday)", "month": "calendar month"}
_PERIOD_START_SQL: dict[Grain, str] = {
    "day": "d",
    "week": "CAST(date_trunc('week', d) AS DATE)",  # ISO weeks start on Monday
    "month": "CAST(date_trunc('month', d) AS DATE)",
}


class TrendPeriod(BaseModel):
    start: date
    end: date  # inclusive
    row_count: int  # rows whose date falls in this period


class TrendPoint(BaseModel):
    value: int | float | None  # None when no row in the period could be used, never 0
    rows_included: int


class TrendSeries(BaseModel):
    status: Literal["calculated", "unavailable"]
    definition: str
    columns_used: list[str]
    rows_included: int | None
    rows_excluded: int | None
    notes: list[str]
    points: list[TrendPoint]  # one per period, in the same order; empty when unavailable


class SalesTrends(BaseModel):
    grain: Grain
    columns_used: dict[TrendRole, str | None]
    date_rule: str
    number_rule: str
    dated_rows: MetricResult
    periods: list[TrendPeriod]
    revenue: TrendSeries
    order_count: TrendSeries
    average_order_value: TrendSeries


def resolve_trend_columns(available: list[str], requested: Mapping[TrendRole, str | None]) -> dict[TrendRole, str | None]:
    """Pick the column for each trends role, by the same rules as the metrics (ColumnMappingError if invalid)."""
    return resolve_columns(available, requested, TREND_ROLES)


# ---------- Trends ----------


def calculate_sales_trends(
    parsed: ParsedCsv, columns: dict[TrendRole, str | None], grain: Grain = DEFAULT_GRAIN
) -> SalesTrends:
    """Load the rows into DuckDB, group them by period, and calculate every series the columns support."""
    if grain not in GRAINS:
        raise ValueError(f"grain must be one of {', '.join(GRAINS)}, not {grain!r}.")
    metric_columns: dict[Role, str | None] = {role: columns[role] for role in ROLES}
    with load_into_duckdb(parsed) as table:
        return _Calculation(table, columns, metric_columns, grain).run()


@dataclass
class _Calculation:
    table: LoadedTable
    columns: dict[TrendRole, str | None]
    metric_columns: dict[Role, str | None]
    grain: Grain

    def run(self) -> SalesTrends:
        date_column = self.columns["order_date"]
        if date_column is None:
            return self._without_periods(
                _unavailable_metric(
                    self._dated_rows_definition("order_date"),
                    "No column named 'order_date'. To use another column, send order_date_column.",
                ),
                "Needs an order date column to group rows by period.",
            )

        revenue_problem = self._create_rows(date_column)
        dated, first, last = self._sql("SELECT COUNT(d), MIN(d), MAX(d) FROM trend_rows")[0]
        dated_rows = self._dated_rows(date_column, dated)
        if dated == 0:
            return self._without_periods(dated_rows, "No row has a usable date, so nothing can be grouped by period.")

        period_count = _count_periods(first, last, self.grain)
        if period_count > MAX_PERIODS:
            dated_rows.notes.insert(0, self._too_many_periods_note(first, last, period_count))
            return self._without_periods(dated_rows, "The dates span too many periods. See dated_rows for details.")

        periods = self._periods(first, last)
        empty = sum(period.row_count == 0 for period in periods)
        if empty:
            dated_rows.notes.append(
                f"{empty} period(s) between {periods[0].start} and {periods[-1].end} have no rows. "
                "They are listed with no values, not zero."
            )
        revenue = self._revenue(periods, revenue_problem)
        return SalesTrends(
            grain=self.grain,
            columns_used=self.columns,
            date_rule=DATE_RULE,
            number_rule=NUMBER_RULE,
            dated_rows=dated_rows,
            periods=periods,
            revenue=revenue,
            order_count=self._order_count(periods),
            average_order_value=self._average_order_value(periods, revenue),
        )

    # ---------- Working table ----------

    def _create_rows(self, date_column: str) -> str | None:
        """Build the working table. Returns why revenue can't be used, if per-row revenue overflows."""
        order_id = self.columns["order_id"]
        oid_sql = "NULL"
        if order_id is not None:
            oid = self.table.identifier(order_id)
            oid_sql = f"CASE WHEN trim({oid}) <> '' THEN {oid} END"
        has_revenue = revenue_source(self.metric_columns) is not None
        value_sql = revenue_value_sql(self.table, self.metric_columns) if has_revenue else "NULL"

        def create(value: str) -> None:
            params = {"date_pattern": DATE_PATTERN.pattern}
            if "$number_pattern" in value:
                params["number_pattern"] = NUMBER_PATTERN
            self.table.connection.execute(
                f"CREATE OR REPLACE TEMP TABLE {ROWS} AS "
                f"SELECT {LINE_COLUMN} AS line, d, {_PERIOD_START_SQL[self.grain]} AS p, v, oid FROM ("
                f"SELECT {LINE_COLUMN}, {_date_sql(self.table.identifier(date_column))} AS d, "
                f"CAST({value} AS DECIMAL(38, 8)) AS v, {oid_sql} AS oid FROM {TABLE})",
                params,
            )

        try:
            create(value_sql)
        except duckdb.OutOfRangeException:
            create("NULL")
            return "The values are too large to total exactly."
        return None

    # ---------- Dates and periods ----------

    def _dated_rows(self, date_column: str, dated: int) -> MetricResult:
        definition = self._dated_rows_definition(date_column)
        excluded = self.table.row_count - dated
        lines = self._lines("d IS NULL", excluded)
        if self.table.row_count == 0:
            return _unavailable_metric(definition, "The file has no data rows.", [date_column])
        if dated == 0:
            return _unavailable_metric(
                definition,
                f"No row has a usable date in '{date_column}'. Dates must be real calendar dates "
                f"written YYYY-MM-DD{lines}.",
                [date_column],
            )
        notes = [f"{excluded} row(s) excluded because '{date_column}' was blank or not a usable date{lines}."] if excluded else []
        return MetricResult(
            status="calculated", value=dated, definition=definition, columns_used=[date_column],
            rows_included=dated, rows_excluded=excluded, notes=notes,
        )

    def _dated_rows_definition(self, date_column: str) -> str:
        return (
            f"Rows with a usable date in '{date_column}'. Only these rows are grouped into periods "
            f"(one per {GRAIN_NAMES[self.grain]})."
        )

    def _too_many_periods_note(self, first: date, last: date, count: int) -> str:
        first_line = self._sql("SELECT MIN(line) FROM trend_rows WHERE d = $d", {"d": first})[0][0]
        last_line = self._sql("SELECT MIN(line) FROM trend_rows WHERE d = $d", {"d": last})[0][0]
        coarser = "Choose a longer period, or check" if self.grain != "month" else "Check"
        return (
            f"The usable dates run from {first} (line {first_line}) to {last} (line {last_line}): "
            f"{count} periods by {self.grain}, more than the limit of {MAX_PERIODS}. "
            f"{coarser} the earliest and latest dates for typing mistakes."
        )

    def _periods(self, first: date, last: date) -> list[TrendPeriod]:
        counts = dict(self._sql("SELECT p, COUNT(*) FROM trend_rows WHERE d IS NOT NULL GROUP BY p"))
        return [
            TrendPeriod(start=start, end=_period_end(start, self.grain), row_count=counts.get(start, 0))
            for start in _period_starts(first, last, self.grain)
        ]

    # ---------- Series ----------

    def _revenue(self, periods: list[TrendPeriod], problem: str | None) -> TrendSeries:
        source = revenue_source(self.metric_columns)
        if source is None:
            return _unavailable_series(
                f"Per period: {_lower_first(REVENUE_FALLBACK_DEFINITION)}", revenue_unavailable_reason(self.metric_columns)
            )
        definition = f"Per period: {_lower_first(source.definition)} Rows without a usable date are excluded."
        if problem is not None:
            return _unavailable_series(definition, problem, source.columns_used)
        try:
            per_period = {
                p: (total, count)
                for p, total, count in self._sql(
                    "SELECT p, SUM(v), COUNT(v) FROM trend_rows WHERE d IS NOT NULL GROUP BY p"
                )
            }
        except duckdb.OutOfRangeException:
            return _unavailable_series(definition, "The values are too large to total exactly.", source.columns_used)

        included = sum(count for _, count in per_period.values())
        names = " or ".join(f"'{name}'" for name in source.columns_used)
        if included == 0:
            return _unavailable_series(definition, f"No dated row has a usable number in {names}.", source.columns_used)

        notes = self._undated_note()
        unusable = self._count("d IS NOT NULL AND v IS NULL")
        if unusable:
            lines = self._lines("d IS NOT NULL AND v IS NULL", unusable)
            notes.append(f"{unusable} dated row(s) excluded because {names} was blank or not a usable number{lines}.")
        negatives = self._count("d IS NOT NULL AND v < 0")
        if negatives:
            notes.append(f"{negatives} row(s) have negative values (possibly returns or refunds); they are included as-is.")

        points = []
        for period in periods:
            total, count = per_period.get(period.start, (None, 0))
            points.append(TrendPoint(value=float(total) if count else None, rows_included=count))
        return TrendSeries(
            status="calculated", definition=definition, columns_used=source.columns_used,
            rows_included=included, rows_excluded=self.table.row_count - included, notes=notes, points=points,
        )

    def _order_count(self, periods: list[TrendPeriod]) -> TrendSeries:
        definition = (
            "Per period: number of distinct order IDs (exact text match). Rows with a blank order ID "
            "or without a usable date are excluded."
        )
        order_id = self.columns["order_id"]
        if order_id is None:
            return _unavailable_series(definition, "No column named 'order_id'. To use another column, send order_id_column.")

        per_period = {
            p: (orders, rows)
            for p, orders, rows in self._sql(
                "SELECT p, COUNT(DISTINCT oid), COUNT(oid) FROM trend_rows WHERE d IS NOT NULL GROUP BY p"
            )
        }
        included = sum(rows for _, rows in per_period.values())
        if included == 0:
            return _unavailable_series(definition, "Every dated row has a blank order ID.", [order_id])

        notes = self._undated_note()
        blank = self._count("d IS NOT NULL AND oid IS NULL")
        if blank:
            notes.append(f"{blank} dated row(s) have a blank order ID{self._lines('d IS NOT NULL AND oid IS NULL', blank)}.")
        spanning = self._sql(
            "SELECT COUNT(*) FROM (SELECT oid FROM trend_rows WHERE d IS NOT NULL AND oid IS NOT NULL "
            "GROUP BY oid HAVING COUNT(DISTINCT p) > 1)"
        )[0][0]
        if spanning:
            notes.append(
                f"{spanning} order(s) have rows in more than one period. Each is counted in every period it "
                "appears in, so the period counts add up to more than the file's distinct orders."
            )

        points = []
        for period in periods:
            orders, rows = per_period.get(period.start, (0, 0))
            points.append(TrendPoint(value=orders if rows else None, rows_included=rows))
        return TrendSeries(
            status="calculated", definition=definition, columns_used=[order_id],
            rows_included=included, rows_excluded=self.table.row_count - included, notes=notes, points=points,
        )

    def _average_order_value(self, periods: list[TrendPeriod], revenue: TrendSeries) -> TrendSeries:
        definition = (
            "Per period: revenue / number of distinct orders, using only rows that have a usable date, "
            "an order ID, and a usable revenue value. Uses the same revenue definition as the revenue trend."
        )
        order_id = self.columns["order_id"]
        if order_id is None:
            return _unavailable_series(
                definition,
                "Needs an order ID column, because one order can span several rows. "
                "No column named 'order_id'; to use another column, send order_id_column.",
            )
        if revenue.status != "calculated":
            return _unavailable_series(definition, "Revenue per period could not be calculated, so neither can this.")

        used = [order_id, *revenue.columns_used]
        condition = "d IS NOT NULL AND oid IS NOT NULL AND v IS NOT NULL"
        try:
            per_period = {
                p: (total, orders, rows)
                for p, total, orders, rows in self._sql(
                    f"SELECT p, SUM(v), COUNT(DISTINCT oid), COUNT(*) FROM trend_rows WHERE {condition} GROUP BY p"
                )
            }
        except duckdb.OutOfRangeException:
            return _unavailable_series(definition, "The values are too large to total exactly.", used)

        included = sum(rows for _, _, rows in per_period.values())
        if included == 0:
            return _unavailable_series(definition, "No dated row has both an order ID and a usable revenue value.", used)
        excluded = self.table.row_count - included
        notes = (
            [f"{excluded} row(s) excluded because the date was not usable, the order ID was blank, or revenue was not usable."]
            if excluded
            else []
        )

        points = []
        for period in periods:
            total, orders, rows = per_period.get(period.start, (None, 0, 0))
            value = float(Decimal(total) / orders) if orders else None
            points.append(TrendPoint(value=value, rows_included=rows))
        return TrendSeries(
            status="calculated", definition=definition, columns_used=used,
            rows_included=included, rows_excluded=excluded, notes=notes, points=points,
        )

    # ---------- Helpers ----------

    def _without_periods(self, dated_rows: MetricResult, reason: str) -> SalesTrends:
        """The result when rows can't be grouped: every series unavailable for the same reason."""
        return SalesTrends(
            grain=self.grain,
            columns_used=self.columns,
            date_rule=DATE_RULE,
            number_rule=NUMBER_RULE,
            dated_rows=dated_rows,
            periods=[],
            revenue=_unavailable_series("Revenue per period.", reason),
            order_count=_unavailable_series("Distinct orders per period.", reason),
            average_order_value=_unavailable_series("Revenue / distinct orders per period.", reason),
        )

    def _undated_note(self) -> list[str]:
        undated = self._count("d IS NULL")
        return [f"{undated} row(s) without a usable date are excluded (see dated_rows)."] if undated else []

    def _sql(self, sql: str, params: dict[str, object] | None = None) -> list[tuple]:
        return self.table.connection.execute(sql, params or {}).fetchall()

    def _count(self, condition: str) -> int:
        return self._sql(f"SELECT COUNT(*) FROM {ROWS} WHERE {condition}")[0][0]

    def _lines(self, condition: str, total: int) -> str:
        """' (lines 4, 7, ...)': the first rows matching a condition, as evidence."""
        return lines_suffix(self.table.connection, ROWS, condition, total)



def _date_sql(text_sql: str) -> str:
    """SQL that turns text into a DATE, or NULL unless it is a usable date (the profiler's rule).

    The pattern checks the shape (YYYY-MM-DD); the cast rejects impossible dates such as
    2026-02-30. Year 0000 is rejected too: DuckDB reads it as 1 BC, Python has no year 0.
    """
    value = f"TRY_CAST(trim({text_sql}) AS DATE)"
    return (
        f"CASE WHEN regexp_full_match(trim({text_sql}), $date_pattern) "
        f"AND {value} >= DATE '0001-01-01' THEN {value} END"
    )


def _period_starts(first: date, last: date, grain: Grain) -> Iterator[date]:
    start, final = _period_start(first, grain), _period_start(last, grain)
    while True:
        yield start
        if start >= final:
            return
        start = _next_period_start(start, grain)


def _count_periods(first: date, last: date, grain: Grain) -> int:
    start, final = _period_start(first, grain), _period_start(last, grain)
    if grain == "day":
        return (final - start).days + 1
    if grain == "week":
        return (final - start).days // 7 + 1
    return (final.year - start.year) * 12 + final.month - start.month + 1


def _period_start(day: date, grain: Grain) -> date:
    if grain == "day":
        return day
    if grain == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _next_period_start(start: date, grain: Grain) -> date:
    if grain == "day":
        return start + timedelta(days=1)
    if grain == "week":
        return start + timedelta(days=7)
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def _period_end(start: date, grain: Grain) -> date:
    if grain == "day":
        return start
    if grain == "week":
        return start + timedelta(days=min(6, (date.max - start).days))  # the calendar ends on 9999-12-31
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _unavailable_metric(definition: str, reason: str, columns_used: list[str] | None = None) -> MetricResult:
    return MetricResult(
        status="unavailable", value=None, definition=definition, columns_used=columns_used or [],
        rows_included=None, rows_excluded=None, notes=[reason],
    )


def _unavailable_series(definition: str, reason: str, columns_used: list[str] | None = None) -> TrendSeries:
    return TrendSeries(
        status="unavailable", definition=definition, columns_used=columns_used or [],
        rows_included=None, rows_excluded=None, notes=[reason], points=[],
    )
