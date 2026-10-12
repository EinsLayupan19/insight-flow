"""Deterministic insights: plain-English findings built only from computed, checkable figures.

Every finding comes from the existing analytics (the same rows, labels, revenue, and date
rules as the metrics, trends, and product and category performance) and states what the
numbers show, with the values, periods, and row counts behind it. It never states why.

Safeguards (THRESHOLDS, returned with every result):
- Only complete periods are compared. A period is complete when the file's usable dates
  cover it from its first to its last day; a partly covered first or last period is left
  out and reported as a caveat. (Complete coverage does not prove every sale was recorded.)
- A comparison needs at least 5 rows in each period, a streak at least 3 consecutive
  complete periods, and an unusual-period check at least 8 complete periods.
- No percentage change is given from a zero or negative baseline.
- When a check can't run, it is listed in not_assessed with the reason, never skipped silently.

SQL safety: queries only use generated identifiers and fixed working-table names; values are
passed as query parameters.
"""

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

import duckdb
from pydantic import BaseModel

from app.analytics.duckdb_loader import TABLE, LoadedTable, load_into_duckdb
from app.analytics.product_performance import PERFORMANCE_ROLES, Breakdown, ProductPerformance, performance_for_table
from app.analytics.retail_metrics import (
    NUMBER_PATTERN,
    ROLES,
    Role,
    resolve_columns,
    revenue_source,
    revenue_unavailable_reason,
    revenue_value_sql,
)
from app.analytics.sales_trends import (
    DEFAULT_GRAIN,
    GRAINS,
    TREND_ROLES,
    Grain,
    SalesTrends,
    TrendPeriod,
    TrendSeries,
    trends_for_table,
)
from app.ingestion.csv_parser import ParsedCsv

InsightRole = Literal["order_date", "product", "category", "order_id", "quantity", "unit_price", "revenue"]
INSIGHT_ROLES: tuple[InsightRole, ...] = ("order_date", "product", "category", *ROLES)

InsightKind = Literal["period_change", "unusual_period", "streak", "mover", "concentration", "negative_revenue", "range"]
KIND_ORDER: tuple[InsightKind, ...] = ("period_change", "unusual_period", "streak", "mover", "concentration", "negative_revenue", "range")
Importance = Literal["high", "medium", "low"]
IMPORTANCE_ORDER: tuple[Importance, ...] = ("high", "medium", "low")
Dimension = Literal["product", "category"]

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
UNITS: dict[Grain, tuple[str, str]] = {"day": ("day", "days"), "week": ("week", "weeks"), "month": ("month", "months")}
SHORTER_GRAIN: dict[Grain, str] = {"month": "weeks", "week": "days"}
DIMENSION_WORDS: dict[Dimension, tuple[str, str]] = {"product": ("product", "products"), "category": ("category", "categories")}


class Thresholds(BaseModel):
    """The safeguards behind every finding. Documented in the README; returned with each result."""

    min_rows_per_period: int = 5
    min_periods_for_streak: int = 3
    min_periods_for_range: int = 3
    min_periods_for_unusual: int = 8
    unusual_score: float = 3.5  # robust z-score: 0.6745 x |value - median| / median absolute deviation
    max_unusual_periods: int = 3
    high_change_percent: float = 20.0
    medium_change_percent: float = 5.0
    high_share_percent: float = 50.0
    medium_share_percent: float = 25.0
    medium_negative_percent: float = 5.0
    concentration_target_percent: float = 80.0


THRESHOLDS = Thresholds()


class DateRange(BaseModel):
    start: date
    end: date


class PartialPeriod(DateRange):
    covered_from: date
    covered_to: date


class Coverage(BaseModel):
    first_date: date | None  # first and last usable dates in the file
    last_date: date | None
    periods: int
    complete_periods: int
    partial_periods: list[PartialPeriod]


class Evidence(BaseModel):
    metric: str
    value: float | int | None
    previous: float | int | None = None
    change: float | None = None
    change_percent: float | None = None  # signed, rounded to 1 decimal; None from a zero or negative baseline
    period: DateRange | None = None
    comparison_period: DateRange | None = None
    rows: int | None = None
    comparison_rows: int | None = None
    label: str | None = None  # the product or category, for per-label findings


class Insight(BaseModel):
    id: str
    kind: InsightKind
    importance: Importance
    title: str
    statement: str  # what the numbers show, from a fixed template; never a cause
    evidence: list[Evidence]
    caveats: list[str]
    questions: list[str]  # things worth checking; not findings


class NotAssessed(BaseModel):
    kind: InsightKind
    title: str
    reason: str


class SalesInsights(BaseModel):
    grain: Grain
    columns_used: dict[InsightRole, str | None]
    definition: str
    thresholds: Thresholds
    coverage: Coverage
    insights: list[Insight]  # most important first
    not_assessed: list[NotAssessed]
    caveats: list[str]  # about the whole file, shown with every finding


def resolve_insight_columns(available: list[str], requested: Mapping[InsightRole, str | None]) -> dict[InsightRole, str | None]:
    """Pick the column for each role, by the same rules as the metrics (ColumnMappingError if invalid)."""
    return resolve_columns(available, requested, INSIGHT_ROLES)


def calculate_insights(parsed: ParsedCsv, columns: dict[InsightRole, str | None], grain: Grain = DEFAULT_GRAIN) -> SalesInsights:
    """Load the rows into DuckDB once, run the trends and performance analytics, and derive findings from them."""
    if grain not in GRAINS:
        raise ValueError(f"grain must be one of {', '.join(GRAINS)}, not {grain!r}.")
    with load_into_duckdb(parsed) as table:
        return _Insights(table, dict(columns), grain).run()


# ---------- Wording helpers ----------


def amount(value: float | Decimal) -> str:
    return f"{value:,.2f}"


def count(value: float | int | Decimal) -> str:
    return f"{int(value):,}" if value == int(value) else f"{value:,.1f}"


def day_text(day: date) -> str:
    return f"{MONTHS[day.month - 1][:3]} {day.day}, {day.year}"


def period_label(period: TrendPeriod | DateRange, grain: Grain) -> str:
    """'March 2026', 'week of Mar 2, 2026', or 'Mar 2, 2026'."""
    if grain == "month":
        return f"{MONTHS[period.start.month - 1]} {period.start.year}"
    if grain == "week":
        return f"week of {day_text(period.start)}"
    return day_text(period.start)


def period_name(period: TrendPeriod | DateRange, grain: Grain) -> str:
    return f"the {period_label(period, grain)}" if grain == "week" else period_label(period, grain)


def period_phrase(period: TrendPeriod | DateRange, grain: Grain) -> str:
    return f"on {period_label(period, grain)}" if grain == "day" else f"in {period_name(period, grain)}"


def capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def plural(n: int, singular: str, plural_form: str) -> str:
    return singular if n == 1 else plural_form


def _decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def _percent(change: Decimal, base: Decimal) -> float | None:
    return None if base <= 0 else float(round(change / base * 100, 1))


@dataclass(frozen=True)
class _Metric:
    key: str
    name: str  # as the subject of a sentence: "Revenue", "Gross sales", "Orders"
    verb: str  # "was" or "were"
    format: Literal["amount", "count"]
    series: TrendSeries
    max_importance: Importance = "high"

    @property
    def lower(self) -> str:
        return self.name[:1].lower() + self.name[1:]

    def text(self, value: float | int | Decimal) -> str:
        return amount(value) if self.format == "amount" else count(value)


# ---------- The calculation ----------


@dataclass
class _Insights:
    table: LoadedTable
    columns: dict[InsightRole, str | None]
    grain: Grain

    def run(self) -> SalesInsights:
        self.trends: SalesTrends = trends_for_table(self.table, {role: self.columns[role] for role in TREND_ROLES}, self.grain)
        self.performance: ProductPerformance = performance_for_table(
            self.table, {role: self.columns[role] for role in PERFORMANCE_ROLES}
        )
        self.metric_columns: dict[Role, str | None] = {role: self.columns[role] for role in ROLES}
        self.insights: list[Insight] = []
        self.not_assessed: list[NotAssessed] = []
        self.caveats: list[str] = []
        self.unit, self.units = UNITS[self.grain]
        self.revenue_name = "Revenue" if self.columns["revenue"] is not None else "Gross sales"

        coverage = self._coverage()
        metrics = self._metrics()
        primary = next((metric for metric in metrics if metric.key in ("revenue", "orders") and metric.series.status == "calculated"), None)

        self._period_changes(metrics)
        self._streak(primary)
        self._range(primary)
        self._unusual(primary)
        for dimension in ("product", "category"):
            self._concentration(dimension)
            self._movers(dimension)
        self._negative_revenue()
        self._file_caveats()

        # A stable sort: within one importance and kind, findings keep the fixed order they were built in
        # (revenue, then orders, then average order value; increases before decreases), so output never varies.
        self.insights.sort(key=lambda item: (IMPORTANCE_ORDER.index(item.importance), KIND_ORDER.index(item.kind)))
        return SalesInsights(
            grain=self.grain,
            columns_used=self.columns,
            definition=(
                f"Findings compare complete {self.units} only: a period is complete when the file's usable dates "
                "cover it from its first to its last day (this does not prove every sale was recorded). Each "
                "finding states what the numbers show and the rows behind it; it never states a reason."
            ),
            thresholds=THRESHOLDS,
            coverage=coverage,
            insights=self.insights,
            not_assessed=self.not_assessed,
            caveats=self.caveats,
        )

    # ---------- Periods ----------

    def _coverage(self) -> Coverage:
        periods = self.trends.periods
        first = last = None
        if periods:
            first, last = self._sql("SELECT MIN(d), MAX(d) FROM trend_rows")[0]
        self.complete: list[int] = []  # indexes of complete periods, oldest first
        partial: list[PartialPeriod] = []
        for index, period in enumerate(periods):
            starts_late = index == 0 and first > period.start
            ends_early = index == len(periods) - 1 and last < period.end
            if starts_late or ends_early:
                covered_from = first if starts_late else period.start
                covered_to = last if ends_early else period.end
                partial.append(PartialPeriod(start=period.start, end=period.end, covered_from=covered_from, covered_to=covered_to))
                self.caveats.append(self._partial_caveat(period, starts_late, ends_early, first, last))
            else:
                self.complete.append(index)
        return Coverage(
            first_date=first, last_date=last, periods=len(periods), complete_periods=len(self.complete), partial_periods=partial
        )

    def _partial_caveat(self, period: TrendPeriod, starts_late: bool, ends_early: bool, first: date, last: date) -> str:
        if starts_late and ends_early:
            covered = f"the data covers {day_text(first)} to {day_text(last)}"
        elif starts_late:
            covered = f"the data starts on {day_text(first)}"
        else:
            covered = f"the data ends on {day_text(last)}"
        return f"{capitalize(period_name(period, self.grain))} is only partly covered ({covered}), so it is left out of comparisons."

    def _eligible(self, index: int) -> bool:
        return self.trends.periods[index].row_count >= THRESHOLDS.min_rows_per_period

    def _periods_problem(self) -> str | None:
        """Why periods can't be used at all (no date column, no usable dates, too many periods), if so."""
        if self.trends.periods:
            return None
        dated = self.trends.dated_rows
        return dated.notes[0] if dated.notes else "No row has a usable date."

    def _comparison_periods(self) -> tuple[int, int] | str:
        """The last two complete periods, or why they can't be compared."""
        problem = self._periods_problem()
        if problem:
            return problem
        eligible = [index for index in self.complete if self._eligible(index)]
        if len(self.complete) < 2:
            hint = f" Try a shorter period, such as {SHORTER_GRAIN[self.grain]}." if self.grain in SHORTER_GRAIN else ""
            return (
                f"Needs 2 complete {self.units} with at least {THRESHOLDS.min_rows_per_period} rows each; "
                f"found {len(eligible)}.{hint}"
            )
        previous, current = self.complete[-2], self.complete[-1]
        for index in (previous, current):
            if not self._eligible(index):
                period = self.trends.periods[index]
                return (
                    f"{capitalize(period_name(period, self.grain))} has {period.row_count} rows, fewer than the "
                    f"{THRESHOLDS.min_rows_per_period} needed for a comparison."
                )
        return previous, current

    def _metrics(self) -> list[_Metric]:
        revenue_verb = "was" if self.revenue_name == "Revenue" else "were"
        return [
            _Metric("revenue", self.revenue_name, revenue_verb, "amount", self.trends.revenue),
            _Metric("orders", "Orders", "were", "count", self.trends.order_count),
            _Metric("average_order_value", "Average order value", "was", "amount", self.trends.average_order_value, "medium"),
        ]

    def _value(self, metric: _Metric, index: int) -> float | int | None:
        return metric.series.points[index].value if metric.series.status == "calculated" else None

    # ---------- Period change ----------

    def _period_changes(self, metrics: list[_Metric]) -> None:
        periods = self._comparison_periods()
        if isinstance(periods, str):
            self.not_assessed.append(NotAssessed(kind="period_change", title="Period comparison", reason=periods))
            return
        previous, current = periods
        for metric in metrics:
            if metric.series.status != "calculated":
                reason = metric.series.notes[0] if metric.series.notes else "Not available."
                self.not_assessed.append(NotAssessed(kind="period_change", title=f"{metric.name} comparison", reason=reason))
                continue
            now, before = self._value(metric, current), self._value(metric, previous)
            if now is None or before is None:
                self.not_assessed.append(
                    NotAssessed(kind="period_change", title=f"{metric.name} comparison", reason=f"A compared period has no usable {metric.lower} values.")
                )
                continue
            self.insights.append(self._change_insight(metric, previous, current, before, now))

    def _change_insight(self, metric: _Metric, previous: int, current: int, before: float | int, now: float | int) -> Insight:
        periods = self.trends.periods
        then_period, now_period = periods[previous], periods[current]
        change = _decimal(now) - _decimal(before)
        percent = _percent(change, _decimal(before))
        when = period_phrase(now_period, self.grain)
        if change == 0:
            title = f"{metric.name} {metric.verb} unchanged {when}"
            statement = f"{metric.name} {metric.verb} {metric.text(now)} {when}, unchanged from {period_name(then_period, self.grain)}."
            importance: Importance = "low"
        else:
            rose = change > 0
            percent_text = f" ({abs(percent):.1f}%)" if percent is not None else ""
            title = (
                f"{metric.name} {'rose' if rose else 'fell'} {abs(percent):.1f}% {when}"
                if percent is not None
                else f"{metric.name} {'rose' if rose else 'fell'} by {metric.text(abs(change))} {when}"
            )
            statement = (
                f"{metric.name} {metric.verb} {metric.text(now)} {when}, {'up' if rose else 'down'} "
                f"{metric.text(abs(change))}{percent_text} from {metric.text(before)} {period_phrase(then_period, self.grain)}."
            )
            if percent is None:
                statement += " No percentage change is shown: the earlier value is zero or negative."
            importance = _change_importance(percent)
        if IMPORTANCE_ORDER.index(importance) < IMPORTANCE_ORDER.index(metric.max_importance):
            importance = metric.max_importance
        return Insight(
            id=f"period_change.{metric.key}",
            kind="period_change",
            importance=importance,
            title=title,
            statement=statement,
            evidence=[
                Evidence(
                    metric=metric.key, value=now, previous=before, change=float(change), change_percent=percent,
                    period=_range(now_period), comparison_period=_range(then_period),
                    rows=now_period.row_count, comparison_rows=then_period.row_count,
                )
            ],
            caveats=[],
            questions=["Check that both periods are recorded completely in the source data."],
        )

    # ---------- Streaks, ranges, unusual periods ----------

    def _streak(self, metric: _Metric | None) -> None:
        if metric is None or self._periods_problem():
            return
        run: list[int] = []  # the latest consecutive complete, eligible periods with values
        for index in reversed(self.complete):
            if run and index != run[-1] - 1:
                break
            if not self._eligible(index) or self._value(metric, index) is None:
                break
            run.append(index)
        run.reverse()
        needed = THRESHOLDS.min_periods_for_streak
        if len(run) < needed:
            self.not_assessed.append(
                NotAssessed(
                    kind="streak", title="Streaks",
                    reason=f"Needs at least {needed} consecutive complete {self.units} with at least "
                    f"{THRESHOLDS.min_rows_per_period} rows each; found {len(run)}.",
                )
            )
            return
        values = [_decimal(self._value(metric, index)) for index in run]
        direction = (values[-1] > values[-2]) - (values[-1] < values[-2])
        steps = 0
        for later, earlier in zip(reversed(values), list(reversed(values))[1:]):
            if (later > earlier) - (later < earlier) != direction or direction == 0:
                break
            steps += 1
        if steps < needed - 1:
            return
        start, end = self.trends.periods[run[-1 - steps]], self.trends.periods[run[-1]]
        verb = "rose" if direction > 0 else "fell"
        self.insights.append(
            Insight(
                id=f"streak.{metric.key}",
                kind="streak",
                importance="medium",
                title=f"{metric.name} {verb} for {steps} consecutive {self.units}",
                statement=(
                    f"{metric.name} {verb} in each of the last {steps} {self.unit}-over-{self.unit} comparisons, from "
                    f"{metric.text(values[-1 - steps])} {period_phrase(start, self.grain)} to {metric.text(values[-1])} "
                    f"{period_phrase(end, self.grain)}."
                ),
                evidence=[
                    Evidence(
                        metric=metric.key, value=float(values[-1]), previous=float(values[-1 - steps]),
                        change=float(values[-1] - values[-1 - steps]), period=_range(end), comparison_period=_range(start),
                    )
                ],
                caveats=[],
                questions=[],
            )
        )

    def _assessable(self, metric: _Metric) -> list[tuple[int, Decimal]]:
        return [
            (index, _decimal(self._value(metric, index)))
            for index in self.complete
            if self._eligible(index) and self._value(metric, index) is not None
        ]

    def _range(self, metric: _Metric | None) -> None:
        if metric is None or self._periods_problem():
            return
        values = self._assessable(metric)
        needed = THRESHOLDS.min_periods_for_range
        if len(values) < needed:
            self.not_assessed.append(
                NotAssessed(
                    kind="range", title="Highest and lowest periods",
                    reason=f"Needs at least {needed} complete {self.units} with at least {THRESHOLDS.min_rows_per_period} "
                    f"rows each; found {len(values)}.",
                )
            )
            return
        high = max(values, key=lambda item: item[1])  # the earliest period wins a tie
        low = min(values, key=lambda item: item[1])
        if high[1] == low[1]:
            return
        high_period, low_period = self.trends.periods[high[0]], self.trends.periods[low[0]]
        self.insights.append(
            Insight(
                id=f"range.{metric.key}",
                kind="range",
                importance="low",
                title=f"Highest and lowest {self.units}",
                statement=(
                    f"Across {len(values)} complete {self.units}, {metric.lower} {metric.verb} highest "
                    f"{period_phrase(high_period, self.grain)} ({metric.text(high[1])}) and lowest "
                    f"{period_phrase(low_period, self.grain)} ({metric.text(low[1])})."
                ),
                evidence=[
                    Evidence(metric=metric.key, value=float(high[1]), period=_range(high_period), rows=high_period.row_count),
                    Evidence(metric=metric.key, value=float(low[1]), period=_range(low_period), rows=low_period.row_count),
                ],
                caveats=[],
                questions=[],
            )
        )

    def _unusual(self, metric: _Metric | None) -> None:
        if metric is None or self._periods_problem():
            return
        values = self._assessable(metric)
        needed = THRESHOLDS.min_periods_for_unusual
        if len(values) < needed:
            self.not_assessed.append(
                NotAssessed(
                    kind="unusual_period", title="Unusual periods",
                    reason=f"Needs at least {needed} complete {self.units} with at least {THRESHOLDS.min_rows_per_period} "
                    f"rows each; found {len(values)}.",
                )
            )
            return
        median = statistics.median(value for _, value in values)
        spread = statistics.median(abs(value - median) for _, value in values)
        if spread == 0:
            self.not_assessed.append(
                NotAssessed(
                    kind="unusual_period", title="Unusual periods",
                    reason=f"The complete {self.units}' values are too similar to measure a typical spread (most are identical).",
                )
            )
            return
        scored = [(Decimal("0.6745") * abs(value - median) / spread, index, value) for index, value in values]
        flagged = sorted((item for item in scored if item[0] > Decimal(str(THRESHOLDS.unusual_score))), key=lambda item: (-item[0], item[1]))
        for _, index, value in flagged[: THRESHOLDS.max_unusual_periods]:
            period = self.trends.periods[index]
            self.insights.append(
                Insight(
                    id=f"unusual_period.{metric.key}.{period.start.isoformat()}",
                    kind="unusual_period",
                    importance="high",
                    title=f"{capitalize(period_label(period, self.grain))} stands out",
                    statement=(
                        f"{metric.name} {metric.verb} {metric.text(value)} {period_phrase(period, self.grain)}, compared with a "
                        f"typical {self.unit} of {metric.text(median)} (the median of {len(values)} complete {self.units})."
                    ),
                    evidence=[Evidence(metric=metric.key, value=float(value), previous=float(median), period=_range(period), rows=period.row_count)],
                    caveats=[],
                    questions=["Check this period for unusually large orders, duplicate uploads, or data entry errors."],
                )
            )

    # ---------- Products and categories ----------

    def _breakdown(self, dimension: Dimension) -> Breakdown:
        return self.performance.products if dimension == "product" else self.performance.categories

    def _concentration(self, dimension: Dimension) -> None:
        breakdown = self._breakdown(dimension)
        singular, plural_form = DIMENSION_WORDS[dimension]
        title = f"{capitalize(singular)} concentration"
        revenue_lower = self.revenue_name.lower()
        reason = None
        if breakdown.status != "calculated":
            reason = breakdown.notes[0]
        elif breakdown.revenue.status != "calculated":
            reason = breakdown.revenue.notes[0]
        elif breakdown.revenue.value is None or breakdown.revenue.value <= 0:
            reason = f"Total {revenue_lower} is zero or negative, so shares can't be compared."
        elif breakdown.group_count < 2:
            reason = f"Only 1 {singular} has {revenue_lower}; there is nothing to compare."
        if reason:
            self.not_assessed.append(NotAssessed(kind="concentration", title=title, reason=reason))
            return

        total = _decimal(breakdown.revenue.value)
        target = total * Decimal(str(THRESHOLDS.concentration_target_percent)) / 100
        running, needed = Decimal(0), None
        for position, group in enumerate(breakdown.groups, start=1):
            running += _decimal(group.revenue or 0)
            if running >= target:
                needed = position
                break
        needed_text = f"{needed:,}" if needed is not None else f"more than {len(breakdown.groups):,}"
        top = breakdown.groups[0]
        share = top.revenue_share or 0.0
        importance: Importance = (
            "high" if share >= THRESHOLDS.high_share_percent else "medium" if share >= THRESHOLDS.medium_share_percent else "low"
        )
        self.insights.append(
            Insight(
                id=f"concentration.{dimension}",
                kind="concentration",
                importance=importance,
                title=f"'{top.label}' accounts for {share:.2f}% of {revenue_lower}",
                statement=(
                    f"Across the whole file, the top {singular}, '{top.label}', accounts for {share:.2f}% of {revenue_lower}, "
                    f"and {needed_text} of {breakdown.group_count:,} {plural_form} together make up at least "
                    f"{THRESHOLDS.concentration_target_percent:.0f}% of it."
                ),
                evidence=[Evidence(metric="revenue_share", value=share, label=top.label, rows=top.row_count)],
                caveats=[],
                questions=[f"Check how much the results depend on these {plural_form}."],
            )
        )

    def _movers(self, dimension: Dimension) -> None:
        singular, plural_form = DIMENSION_WORDS[dimension]
        title = f"{capitalize(singular)} movers"
        breakdown = self._breakdown(dimension)
        periods = self._comparison_periods()
        reason = None
        if isinstance(periods, str):
            reason = periods
        elif breakdown.status != "calculated":
            reason = breakdown.notes[0]
        elif self.trends.revenue.status != "calculated":
            reason = self.trends.revenue.notes[0]
        if reason:
            self.not_assessed.append(NotAssessed(kind="mover", title=title, reason=reason))
            return

        previous, current = periods  # type: ignore[misc]
        then_period, now_period = self.trends.periods[previous], self.trends.periods[current]
        try:
            rows = self._sql(
                f"SELECT r.{dimension}, SUM(t.v) FILTER (WHERE t.p = $then), COUNT(*) FILTER (WHERE t.p = $then), "
                f"SUM(t.v) FILTER (WHERE t.p = $now), COUNT(*) FILTER (WHERE t.p = $now) "
                f"FROM trend_rows AS t JOIN performance_rows AS r ON t.line = r.line "
                f"WHERE r.{dimension} IS NOT NULL AND t.p IN ($then, $now) GROUP BY r.{dimension}",
                {"then": then_period.start, "now": now_period.start},
            )
        except duckdb.OutOfRangeException:
            self.not_assessed.append(NotAssessed(kind="mover", title=title, reason="The values are too large to total exactly."))
            return

        minimum = THRESHOLDS.min_rows_per_period
        changes = []
        for label, before, before_rows, now, now_rows in rows:
            if before_rows + now_rows < minimum:
                continue
            if (before_rows and before is None) or (now_rows and now is None):
                continue  # rows without a usable value: no figure to compare
            changes.append((label, Decimal(before or 0), Decimal(now or 0)))
        if not changes:
            self.not_assessed.append(
                NotAssessed(kind="mover", title=title, reason=f"No {singular} has at least {minimum} rows in these two {self.units}.")
            )
            return

        revenue_lower = self.revenue_name.lower()
        ordered = sorted(changes, key=lambda item: (-(item[2] - item[1]), item[0].encode("utf-8")))
        candidates = {
            "increase": ordered[0] if ordered[0][2] > ordered[0][1] else None,
            "decrease": min(changes, key=lambda item: (item[2] - item[1], item[0].encode("utf-8"))),
        }
        if candidates["decrease"][2] >= candidates["decrease"][1]:
            candidates["decrease"] = None
        for direction, mover in candidates.items():
            if mover is None:
                continue
            label, before, now = mover
            change = now - before
            percent = _percent(change, before)
            percent_text = f" ({abs(percent):.1f}%)" if percent is not None else ""
            self.insights.append(
                Insight(
                    id=f"mover.{dimension}.{direction}",
                    kind="mover",
                    importance="medium",
                    title=f"'{label}' had the largest {direction} in {revenue_lower}",
                    statement=(
                        f"'{label}' had {revenue_lower} of {amount(now)} {period_phrase(now_period, self.grain)}, "
                        f"{'up' if change > 0 else 'down'} {amount(abs(change))}{percent_text} from {amount(before)} "
                        f"{period_phrase(then_period, self.grain)}, the largest {direction} among {len(changes):,} "
                        f"{plural(len(changes), singular, plural_form)} with at least {minimum} rows in these two {self.units}."
                    ),
                    evidence=[
                        Evidence(
                            metric="revenue", label=label, value=float(now), previous=float(before), change=float(change),
                            change_percent=percent, period=_range(now_period), comparison_period=_range(then_period),
                        )
                    ],
                    caveats=[],
                    questions=[f"Check what changed for this {singular} between these {self.units}."],
                )
            )

    # ---------- Negative revenue and file caveats ----------

    def _negative_revenue(self) -> None:
        if revenue_source(self.metric_columns) is None:
            self.not_assessed.append(
                NotAssessed(kind="negative_revenue", title="Negative revenue", reason=revenue_unavailable_reason(self.metric_columns))
            )
            return
        value_sql = revenue_value_sql(self.table, self.metric_columns)
        try:
            negatives, negative_total, positive_total = self._sql(
                f"SELECT COUNT(*) FILTER (WHERE v < 0), SUM(v) FILTER (WHERE v < 0), SUM(v) FILTER (WHERE v > 0) "
                f"FROM (SELECT CAST({value_sql} AS DECIMAL(38, 8)) AS v FROM {TABLE})",
                {"number_pattern": NUMBER_PATTERN},
            )[0]
        except duckdb.OutOfRangeException:
            return
        if not negatives:
            return
        revenue_lower = self.revenue_name.lower()
        statement = f"{negatives:,} {plural(negatives, 'row has', 'rows have')} negative {revenue_lower}, totalling {amount(negative_total)}"
        percent = None
        if positive_total:
            percent = float(round(abs(negative_total) / positive_total * 100, 1))
            statement += f", equal to {percent:.1f}% of the positive {revenue_lower} in the file"
        self.insights.append(
            Insight(
                id="negative_revenue",
                kind="negative_revenue",
                importance="medium" if percent is not None and percent >= THRESHOLDS.medium_negative_percent else "low",
                title=f"Negative {revenue_lower} on {negatives:,} {plural(negatives, 'row', 'rows')}",
                statement=statement + ".",
                evidence=[Evidence(metric="negative_revenue", value=float(negative_total), change_percent=percent, rows=negatives)],
                caveats=[],
                questions=["Negative values often record returns or refunds. Check how this file records them."],
            )
        )

    def _file_caveats(self) -> None:
        dated = self.trends.dated_rows
        if dated.status == "calculated" and dated.rows_excluded:
            self.caveats.append(f"{dated.rows_excluded:,} row(s) have no usable date and are left out of period comparisons.")
        empty = [self.trends.periods[index] for index in self.complete if self.trends.periods[index].row_count == 0]
        if empty:
            names = ", ".join(period_label(period, self.grain) for period in empty[:5]) + (", ..." if len(empty) > 5 else "")
            self.caveats.append(
                f"{len(empty)} complete {plural(len(empty), self.unit, self.units)} "
                f"{plural(len(empty), 'has', 'have')} no rows: {names}."
            )
        duplicates = self._duplicate_rows()
        if duplicates:
            self.caveats.append(f"{duplicates:,} exact duplicate row(s) are counted as-is in every figure.")
        for dimension in ("product", "category"):
            breakdown = self._breakdown(dimension)
            if any(group.similar_labels for group in breakdown.groups):
                self.caveats.append(
                    f"Some {DIMENSION_WORDS[dimension][0]} labels differ only by letter case or spacing; they are counted separately."
                )
        if any(len(group.categories) > 1 for group in self.performance.products.groups):
            self.caveats.append("Some products appear under more than one category.")

    def _duplicate_rows(self) -> int:
        if self.table.row_count == 0:
            return 0
        columns = ", ".join(self.table.identifier(name) for name in self.table.identifiers)
        distinct = self._sql(f"SELECT COUNT(*) FROM (SELECT DISTINCT {columns} FROM {TABLE})")[0][0]
        return self.table.row_count - distinct

    def _sql(self, sql: str, params: dict[str, object] | None = None) -> list[tuple]:
        return self.table.connection.execute(sql, params or {}).fetchall()


def _change_importance(percent: float | None) -> Importance:
    if percent is None:
        return "medium"
    if abs(percent) >= THRESHOLDS.high_change_percent:
        return "high"
    return "medium" if abs(percent) >= THRESHOLDS.medium_change_percent else "low"


def _range(period: TrendPeriod) -> DateRange:
    return DateRange(start=period.start, end=period.end)
