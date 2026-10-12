"""Product and category performance, calculated with DuckDB: revenue, quantity, and orders per label.

The rules are the retail metrics' rules, applied per product and per category:
- Columns are matched by exact name (`product`, `category`, plus the metrics' `order_id`,
  `quantity`, `unit_price`, `revenue`) unless the caller names another column.
- Revenue per row is the same value total_revenue uses, with the same number rule.
- A label is the cell's exact text after trimming surrounding spaces. Blank labels are
  excluded and counted, with line numbers. Labels that differ only by letter case or
  inner spacing are flagged, never merged. Nothing is guessed.
- Groups are ranked by revenue (or quantity, or row count when revenue is unavailable),
  highest first; ties are broken by label in a fixed text order, so a ranking never changes
  between runs. At most 1,000 groups are listed; the rest are summarized so totals still add up.

SQL safety: queries only contain generated identifiers (c0, c1, ...) from the loader and
fixed names chosen here. Values and patterns are passed as query parameters.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
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
    number_sql,
    resolve_columns,
    revenue_source,
    revenue_unavailable_reason,
    revenue_value_sql,
)
from app.ingestion.csv_parser import ParsedCsv

Dimension = Literal["product", "category"]
DIMENSIONS: tuple[Dimension, ...] = ("product", "category")
RankedBy = Literal["revenue", "quantity", "row_count"]

PerformanceRole = Literal["product", "category", "order_id", "quantity", "unit_price", "revenue"]
PERFORMANCE_ROLES: tuple[PerformanceRole, ...] = ("product", "category", *ROLES)

MAX_GROUPS = 1000
MAX_LABEL_EXAMPLES = 5
ROWS = "performance_rows"  # working table: one row per uploaded row, with its labels and values
GROUPS = "performance_groups"  # working table: one row per label of the breakdown being calculated
TOO_LARGE = "The values are too large to total exactly."

LABEL_RULE = (
    "A product or category is the cell's exact text after trimming surrounding spaces. Blank cells are "
    "excluded and counted. Labels that differ only by letter case or inner spacing (Green Tea, green tea, "
    "Green  Tea) are kept separate and flagged, never merged."
)


class PerformanceGroup(BaseModel):
    label: str
    row_count: int
    revenue: float | None  # None when no row of the group has a usable value, never 0
    revenue_share: float | None  # percent of the breakdown's total revenue, rounded to 2 decimals
    quantity: float | None
    order_count: int | None
    similar_labels: list[str]  # other labels that differ from this one only by case or spacing
    categories: list[str]  # products only: the categories its rows are filed under
    product_count: int | None  # categories only: distinct products among its rows


class RemainingGroups(BaseModel):
    """Every group past the first 1,000, summarized so the totals still add up."""

    group_count: int
    row_count: int
    revenue: float | None
    quantity: float | None
    order_count: int | None  # distinct orders among the remaining groups' rows


class Breakdown(BaseModel):
    dimension: Dimension
    status: Literal["calculated", "unavailable"]
    definition: str
    columns_used: list[str]
    rows_included: int | None  # rows with a label
    rows_excluded: int | None
    notes: list[str]
    ranked_by: RankedBy | None
    group_count: int  # all distinct labels, listed or not
    groups: list[PerformanceGroup]  # at most 1,000, in rank order
    remaining: RemainingGroups | None
    # Totals over every labelled row (value), with each measure's own definition and evidence.
    revenue: MetricResult
    quantity: MetricResult
    order_count: MetricResult


class ProductPerformance(BaseModel):
    columns_used: dict[PerformanceRole, str | None]
    label_rule: str
    number_rule: str
    products: Breakdown
    categories: Breakdown


def resolve_performance_columns(
    available: list[str], requested: Mapping[PerformanceRole, str | None]
) -> dict[PerformanceRole, str | None]:
    """Pick the column for each role, by the same rules as the metrics (ColumnMappingError if invalid)."""
    return resolve_columns(available, requested, PERFORMANCE_ROLES)


def calculate_product_performance(parsed: ParsedCsv, columns: dict[PerformanceRole, str | None]) -> ProductPerformance:
    """Load the rows into DuckDB and break revenue, quantity, and orders down by product and by category."""
    with load_into_duckdb(parsed) as table:
        return performance_for_table(table, columns)


def performance_for_table(table: LoadedTable, columns: Mapping[PerformanceRole, str | None]) -> ProductPerformance:
    """Performance for rows already loaded into DuckDB. Leaves the working table performance_rows in the connection."""
    metric_columns: dict[Role, str | None] = {role: columns[role] for role in ROLES}
    calculation = _Calculation(table, dict(columns), metric_columns)
    revenue_problem = calculation.create_rows()
    return ProductPerformance(
        columns_used=dict(columns),
        label_rule=LABEL_RULE,
        number_rule=NUMBER_RULE,
        products=calculation.breakdown("product", revenue_problem),
        categories=calculation.breakdown("category", revenue_problem),
    )


@dataclass
class _Calculation:
    table: LoadedTable
    columns: dict[PerformanceRole, str | None]
    metric_columns: dict[Role, str | None]

    # ---------- Working table ----------

    def create_rows(self) -> str | None:
        """Build the working table. Returns why revenue can't be used, if per-row revenue overflows."""
        has_revenue = revenue_source(self.metric_columns) is not None
        value_sql = revenue_value_sql(self.table, self.metric_columns) if has_revenue else "NULL"
        try:
            self._create_rows(value_sql)
        except duckdb.OutOfRangeException:
            self._create_rows("NULL")
            return TOO_LARGE
        return None

    def _create_rows(self, value_sql: str) -> None:
        quantity = self.columns["quantity"]
        order_id = self.columns["order_id"]
        quantity_sql = number_sql(self.table, quantity) if quantity else "NULL"
        oid_sql = "NULL"
        if order_id is not None:
            oid = self.table.identifier(order_id)
            oid_sql = f"CASE WHEN trim({oid}) <> '' THEN {oid} END"
        sql = (
            f"CREATE OR REPLACE TEMP TABLE {ROWS} AS SELECT {LINE_COLUMN} AS line, "
            f"{self._label_sql('product')} AS product, {self._label_sql('category')} AS category, "
            f"CAST({value_sql} AS DECIMAL(38, 8)) AS v, CAST({quantity_sql} AS DECIMAL(38, 8)) AS q, "
            f"{oid_sql} AS oid FROM {TABLE}"
        )
        params = {"number_pattern": NUMBER_PATTERN} if "$number_pattern" in sql else {}
        self.table.connection.execute(sql, params)

    def _label_sql(self, dimension: Dimension) -> str:
        column = self.columns[dimension]
        if column is None:
            return "CAST(NULL AS VARCHAR)"
        return f"NULLIF(trim({self.table.identifier(column)}), '')"

    # ---------- One breakdown ----------

    def breakdown(self, dimension: Dimension, revenue_problem: str | None) -> Breakdown:
        column = self.columns[dimension]
        if column is None:
            return _unavailable_breakdown(
                dimension, f"No column named '{dimension}'. To use another column, send {dimension}_column.", []
            )
        if self.table.row_count == 0:
            return _unavailable_breakdown(dimension, "The file has no data rows.", [column])

        d = dimension  # a fixed column name of the working table, never user input
        labelled = self._count(f"{d} IS NOT NULL")
        blank = self.table.row_count - labelled
        if labelled == 0:
            return _unavailable_breakdown(dimension, f"Every row has a blank {dimension}{self._lines(f'{d} IS NULL', blank)}.", [column])

        revenue_ok = revenue_problem is None and revenue_source(self.metric_columns) is not None and self._sums(d, "v")
        quantity_ok = self.columns["quantity"] is not None and self._sums(d, "q")
        orders_ok = self.columns["order_id"] is not None
        ranked_by: RankedBy = "revenue" if revenue_ok else "quantity" if quantity_ok else "row_count"
        self._create_groups(d, ranked_by, revenue_ok, quantity_ok, orders_ok)

        group_count = self._sql(f"SELECT COUNT(*) FROM {GROUPS}")[0][0]
        revenue = self._revenue(dimension, revenue_ok, revenue_problem)
        quantity = self._quantity(dimension, quantity_ok)
        order_count = self._order_count(dimension, orders_ok)
        similar = self._similar_labels(d)
        groups = self._listed_groups(dimension, revenue, similar)

        notes = []
        if blank:
            notes.append(f"{blank} row(s) have a blank {dimension}{self._lines(f'{d} IS NULL', blank)}. They are not in any group.")
        if group_count > MAX_GROUPS:
            notes.append(
                f"Showing the top {MAX_GROUPS:,} of {group_count:,} {dimension_plural(dimension)} by {ranked_by.replace('_', ' ')}. "
                f"The other {group_count - MAX_GROUPS:,} are summarized in remaining."
            )
        notes.extend(_similar_note(similar))
        if dimension == "product" and self.columns["category"] is not None:
            notes.extend(self._multi_category_note())

        return Breakdown(
            dimension=dimension,
            status="calculated",
            definition=(
                f"One group per distinct {dimension} label (exact text after trimming surrounding spaces). "
                f"Ranked by {ranked_by.replace('_', ' ')}, highest first; ties are broken by label."
            ),
            columns_used=[column],
            rows_included=labelled,
            rows_excluded=blank,
            notes=notes,
            ranked_by=ranked_by,
            group_count=group_count,
            groups=groups,
            remaining=self._remaining(d, revenue_ok, quantity_ok, orders_ok) if group_count > MAX_GROUPS else None,
            revenue=revenue,
            quantity=quantity,
            order_count=order_count,
        )

    def _sums(self, d: str, value: str) -> bool:
        """Whether every group's sum (and the overall sum) fits the exact decimal type."""
        try:
            self._sql(f"SELECT SUM({value}) FROM {ROWS} WHERE {d} IS NOT NULL GROUP BY {d}")
            self._sql(f"SELECT SUM({value}) FROM {ROWS} WHERE {d} IS NOT NULL")
        except duckdb.OutOfRangeException:
            return False
        return True

    def _create_groups(self, d: str, ranked_by: RankedBy, revenue_ok: bool, quantity_ok: bool, orders_ok: bool) -> None:
        # Binary (code point) order makes ties come out the same on every run and every machine.
        self._sql(
            f"CREATE OR REPLACE TEMP TABLE {GROUPS} AS SELECT *, "
            f"ROW_NUMBER() OVER (ORDER BY {ranked_by} DESC NULLS LAST, label ASC) AS rank FROM ("
            f"SELECT {d} AS label, COUNT(*) AS row_count, "
            f"{'SUM(v)' if revenue_ok else 'NULL'} AS revenue, "
            f"{'SUM(q)' if quantity_ok else 'NULL'} AS quantity, "
            f"{'COUNT(DISTINCT oid)' if orders_ok else 'NULL'} AS order_count, COUNT(oid) AS order_rows "
            f"FROM {ROWS} WHERE {d} IS NOT NULL GROUP BY {d})"
        )

    # ---------- Measures ----------

    def _revenue(self, dimension: Dimension, ok: bool, problem: str | None) -> MetricResult:
        source = revenue_source(self.metric_columns)
        if source is None:
            return _unavailable_metric(REVENUE_FALLBACK_DEFINITION, revenue_unavailable_reason(self.metric_columns))
        definition = (
            f"Per {dimension}: {_lower_first(source.definition)} Share is this revenue as a percentage of the total "
            "over all labelled rows, rounded to 2 decimals."
        )
        if not ok:
            return _unavailable_metric(definition, problem or TOO_LARGE, source.columns_used)
        return self._measure(dimension, "v", definition, source.columns_used, " or ".join(f"'{c}'" for c in source.columns_used))

    def _quantity(self, dimension: Dimension, ok: bool) -> MetricResult:
        definition = f"Per {dimension}: sum of the quantity column. Negative quantities (for example returns) are included as-is."
        quantity = self.columns["quantity"]
        if quantity is None:
            return _unavailable_metric(definition, "No column named 'quantity'. To use another column, send quantity_column.")
        if not ok:
            return _unavailable_metric(definition, TOO_LARGE, [quantity])
        return self._measure(dimension, "q", definition, [quantity], f"'{quantity}'")

    def _measure(self, dimension: Dimension, value: str, definition: str, columns_used: list[str], names: str) -> MetricResult:
        d = dimension
        total, included, negatives = self._sql(
            f"SELECT SUM({value}), COUNT({value}), COUNT(*) FILTER (WHERE {value} < 0) FROM {ROWS} WHERE {d} IS NOT NULL"
        )[0]
        if included == 0:
            return _unavailable_metric(definition, f"No row with a {dimension} has a usable number in {names}.", columns_used)

        notes = []
        unusable = self._count(f"{d} IS NOT NULL AND {value} IS NULL")
        if unusable:
            notes.append(
                f"{unusable} row(s) with a {dimension} excluded because {names} was blank or not a usable number"
                f"{self._lines(f'{d} IS NOT NULL AND {value} IS NULL', unusable)}."
            )
        if negatives:
            notes.append(f"{negatives} row(s) have negative values (possibly returns or refunds); they are included as-is.")
        if value == "v" and total <= 0:
            notes.append("Shares are left empty because total revenue is not positive.")
        return MetricResult(
            status="calculated", value=float(total), definition=definition, columns_used=columns_used,
            rows_included=included, rows_excluded=self.table.row_count - included, notes=notes,
        )

    def _order_count(self, dimension: Dimension, ok: bool) -> MetricResult:
        definition = (
            f"Per {dimension}: number of distinct order IDs (exact text match) among its rows. "
            "Rows with a blank order ID are excluded."
        )
        order_id = self.columns["order_id"]
        if not ok or order_id is None:
            return _unavailable_metric(definition, "No column named 'order_id'. To use another column, send order_id_column.")
        d = dimension
        total, included = self._sql(f"SELECT COUNT(DISTINCT oid), COUNT(oid) FROM {ROWS} WHERE {d} IS NOT NULL")[0]
        if included == 0:
            return _unavailable_metric(definition, f"Every row with a {dimension} has a blank order ID.", [order_id])

        notes = []
        blank = self._count(f"{d} IS NOT NULL AND oid IS NULL")
        if blank:
            notes.append(f"{blank} row(s) with a {dimension} have a blank order ID{self._lines(f'{d} IS NOT NULL AND oid IS NULL', blank)}.")
        counted = self._sql(f"SELECT SUM(order_count) FROM {GROUPS}")[0][0] or 0
        if counted > total:
            notes.append(
                f"An order with several {dimension_plural(dimension)} is counted under each, so the "
                f"{dimension} counts add up to {counted:,}, more than the {total:,} distinct orders."
            )
        return MetricResult(
            status="calculated", value=total, definition=definition, columns_used=[order_id],
            rows_included=included, rows_excluded=self.table.row_count - included, notes=notes,
        )

    # ---------- Groups ----------

    def _listed_groups(self, dimension: Dimension, revenue: MetricResult, similar: dict[str, list[str]]) -> list[PerformanceGroup]:
        rows = self._sql(
            f"SELECT label, row_count, revenue, quantity, order_count, order_rows FROM {GROUPS} "
            f"WHERE rank <= {MAX_GROUPS} ORDER BY rank"
        )
        total: Decimal | None = None
        if revenue.status == "calculated":  # the exact sum, not the rounded float in the response
            total = self._sql(f"SELECT SUM(v) FROM {ROWS} WHERE {dimension} IS NOT NULL")[0][0]
        categories = self._categories_by_product() if dimension == "product" and self.columns["category"] else {}
        products = self._product_counts() if dimension == "category" and self.columns["product"] else None

        groups = []
        for label, row_count, group_revenue, quantity, order_count, order_rows in rows:
            share = None
            if group_revenue is not None and total is not None and total > 0:
                share = float(round(Decimal(group_revenue) / total * 100, 2))
            groups.append(
                PerformanceGroup(
                    label=label,
                    row_count=row_count,
                    revenue=None if group_revenue is None else float(group_revenue),
                    revenue_share=share,
                    quantity=None if quantity is None else float(quantity),
                    order_count=order_count if order_rows else None,
                    similar_labels=[other for other in similar.get(label, []) if other != label],
                    categories=categories.get(label, []),
                    product_count=None if products is None else products.get(label, 0),
                )
            )
        return groups

    def _remaining(self, d: str, revenue_ok: bool, quantity_ok: bool, orders_ok: bool) -> RemainingGroups:
        group_count, row_count, revenue, quantity, orders, order_rows = self._sql(
            f"SELECT COUNT(DISTINCT r.{d}), COUNT(*), SUM(r.v), SUM(r.q), COUNT(DISTINCT r.oid), COUNT(r.oid) "
            f"FROM {ROWS} AS r JOIN {GROUPS} AS g ON r.{d} = g.label WHERE g.rank > {MAX_GROUPS}"
        )[0]
        return RemainingGroups(
            group_count=group_count,
            row_count=row_count,
            revenue=float(revenue) if revenue_ok and revenue is not None else None,
            quantity=float(quantity) if quantity_ok and quantity is not None else None,
            order_count=orders if orders_ok and order_rows else None,
        )

    def _similar_labels(self, d: str) -> dict[str, list[str]]:
        """Labels that differ from another label only by letter case or inner spacing, by label."""
        rows = self._sql(
            f"SELECT label, lower(regexp_replace(label, '\\s+', ' ', 'g')) AS key FROM "
            f"(SELECT DISTINCT {d} AS label FROM {ROWS} WHERE {d} IS NOT NULL)"
        )
        by_key: dict[str, list[str]] = defaultdict(list)
        for label, key in rows:
            by_key[key].append(label)
        similar: dict[str, list[str]] = {}
        for labels in by_key.values():
            if len(labels) > 1:
                for label in labels:
                    similar[label] = sorted(labels)
        return similar

    def _categories_by_product(self) -> dict[str, list[str]]:
        rows = self._sql(
            f"SELECT DISTINCT r.product, r.category FROM {ROWS} AS r JOIN {GROUPS} AS g ON r.product = g.label "
            f"WHERE g.rank <= {MAX_GROUPS} AND r.category IS NOT NULL"
        )
        categories: dict[str, list[str]] = defaultdict(list)
        for product, category in rows:
            categories[product].append(category)
        return {product: sorted(names) for product, names in categories.items()}

    def _product_counts(self) -> dict[str, int]:
        rows = self._sql(f"SELECT category, COUNT(DISTINCT product) FROM {ROWS} WHERE category IS NOT NULL GROUP BY category")
        return dict(rows)

    def _multi_category_note(self) -> list[str]:
        products = (
            f"SELECT product, list(DISTINCT category) AS names FROM {ROWS} WHERE product IS NOT NULL AND category IS NOT NULL "
            "GROUP BY product HAVING COUNT(DISTINCT category) > 1"
        )
        count = self._sql(f"SELECT COUNT(*) FROM ({products})")[0][0]
        if count == 0:
            return []
        rows = self._sql(f"SELECT product, names FROM ({products}) ORDER BY product LIMIT {MAX_LABEL_EXAMPLES}")
        examples = "; ".join(f"'{product}' ({', '.join(sorted(names))})" for product, names in rows)
        more = "; ..." if count > MAX_LABEL_EXAMPLES else ""
        return [f"{count} product(s) appear under more than one category: {examples}{more}."]

    # ---------- Helpers ----------

    def _sql(self, sql: str, params: dict[str, object] | None = None) -> list[tuple]:
        return self.table.connection.execute(sql, params or {}).fetchall()

    def _count(self, condition: str) -> int:
        return self._sql(f"SELECT COUNT(*) FROM {ROWS} WHERE {condition}")[0][0]

    def _lines(self, condition: str, total: int) -> str:
        return lines_suffix(self.table.connection, ROWS, condition, total)


def dimension_plural(dimension: Dimension) -> str:
    return "products" if dimension == "product" else "categories"


def _similar_note(similar: dict[str, list[str]]) -> list[str]:
    families = sorted({tuple(labels) for labels in similar.values()})
    if not families:
        return []
    examples = "; ".join(" / ".join(f"'{label}'" for label in family) for family in families[:MAX_LABEL_EXAMPLES])
    more = "; ..." if len(families) > MAX_LABEL_EXAMPLES else ""
    return [
        f"{len(families)} set(s) of labels differ only by letter case or spacing and are kept separate: "
        f"{examples}{more}. Fix the labels in the file if they mean the same thing."
    ]


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _unavailable_metric(definition: str, reason: str, columns_used: list[str] | None = None) -> MetricResult:
    return MetricResult(
        status="unavailable", value=None, definition=definition, columns_used=columns_used or [],
        rows_included=None, rows_excluded=None, notes=[reason],
    )


def _unavailable_breakdown(dimension: Dimension, reason: str, columns_used: list[str]) -> Breakdown:
    """A breakdown that can't be calculated: no groups, and every measure unavailable for the same reason."""
    measure_reason = f"Needs {dimension} labels to group rows. See the {dimension} breakdown's notes."
    return Breakdown(
        dimension=dimension,
        status="unavailable",
        definition=f"One group per distinct {dimension} label.",
        columns_used=columns_used,
        rows_included=None,
        rows_excluded=None,
        notes=[reason],
        ranked_by=None,
        group_count=0,
        groups=[],
        remaining=None,
        revenue=_unavailable_metric(f"Revenue per {dimension}.", measure_reason),
        quantity=_unavailable_metric(f"Quantity per {dimension}.", measure_reason),
        order_count=_unavailable_metric(f"Distinct orders per {dimension}.", measure_reason),
    )
