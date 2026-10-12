"""Unit tests for deterministic insights: comparisons, safeguards, wording, and honesty rules.

Every fixture is built so its expected figures can be checked by hand. Rows are spread over
a period on consecutive days; `first_day` / `last_day` control whether the file's dates
cover the first and last periods completely.
"""

import copy
import re
from datetime import date, timedelta

import pytest

from app.analytics.insights import (
    THRESHOLDS,
    Insight,
    SalesInsights,
    calculate_insights,
    resolve_insight_columns,
)
from app.analytics.retail_metrics import ColumnMappingError
from app.ingestion.csv_parser import ParsedCsv, parse_csv

HEADER = "order_id,order_date,product,category,revenue"
BANNED = re.compile(r"\b(because|due to|caused|causes|driven by|drove|led to|resulted in|as a result|thanks to)\b", re.I)


def month_rows(month: str, values: list[float], first_day: int = 1, last_day: int | None = None, product: str = "A") -> list[str]:
    """One row per value, on consecutive days from first_day; the last row on last_day if given."""
    rows = []
    for i, value in enumerate(values):
        day = last_day if last_day is not None and i == len(values) - 1 else first_day + i
        rows.append(f"{month}-{i},{month}-{day:02d},{product},General,{value}")
    return rows


def week_rows(monday: date, values: list[float], last_on_sunday: bool = False, product: str = "A") -> list[str]:
    rows = []
    for i, value in enumerate(values):
        day = monday + timedelta(days=6 if last_on_sunday and i == len(values) - 1 else i)
        rows.append(f"{monday}-{i},{day},{product},General,{value}")
    return rows


def insights_for(rows: list[str], grain: str = "month", header: str = HEADER, **requested: str) -> SalesInsights:
    parsed = parse_csv((header + "\n" + "\n".join(rows) + "\n").encode("utf-8"))
    return calculate_insights(parsed, resolve_insight_columns(parsed.columns, requested), grain)


def find(result: SalesInsights, insight_id: str) -> Insight:
    return next(item for item in result.insights if item.id == insight_id)


def ids(result: SalesInsights) -> list[str]:
    return [item.id for item in result.insights]


def not_assessed(result: SalesInsights, kind: str) -> list[str]:
    return [check.reason for check in result.not_assessed if check.kind == kind]


# Jan 100 (5 rows), Feb 150 (5 rows), Mar 120 (6 rows); the dates cover all three months.
THREE_MONTHS = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6, last_day=31)


# ---------- Period comparison ----------


def test_the_latest_complete_month_is_compared_with_the_one_before() -> None:
    result = insights_for(THREE_MONTHS)

    revenue = find(result, "period_change.revenue")
    assert revenue.title == "Revenue fell 20.0% in March 2026"
    assert revenue.statement == "Revenue was 120.00 in March 2026, down 30.00 (20.0%) from 150.00 in February 2026."
    assert revenue.importance == "high"
    evidence = revenue.evidence[0]
    assert (evidence.value, evidence.previous, evidence.change, evidence.change_percent) == (120.0, 150.0, -30.0, -20.0)
    assert (evidence.period.start, evidence.period.end) == (date(2026, 3, 1), date(2026, 3, 31))
    assert (evidence.comparison_period.start, evidence.comparison_period.end) == (date(2026, 2, 1), date(2026, 2, 28))
    assert (evidence.rows, evidence.comparison_rows) == (6, 5)


def test_orders_and_average_order_value_are_compared_too() -> None:
    result = insights_for(THREE_MONTHS)

    assert find(result, "period_change.orders").statement == "Orders were 6 in March 2026, up 1 (20.0%) from 5 in February 2026."
    aov = find(result, "period_change.average_order_value")
    assert aov.statement == "Average order value was 20.00 in March 2026, down 10.00 (33.3%) from 30.00 in February 2026."
    assert aov.importance == "medium"  # a ratio of the other two: never ranked above them


def test_gross_sales_are_named_like_the_metrics() -> None:
    rows = [row.replace(",General,", ",General,1,") for row in THREE_MONTHS]  # quantity 1 x unit_price
    result = insights_for(rows, header="order_id,order_date,product,category,quantity,unit_price")

    assert find(result, "period_change.revenue").statement.startswith("Gross sales were 120.00 in March 2026")


def test_a_partial_last_month_is_left_out_of_comparisons() -> None:
    rows = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6)  # ends Mar 6

    result = insights_for(rows)

    assert find(result, "period_change.revenue").statement == (
        "Revenue was 150.00 in February 2026, up 50.00 (50.0%) from 100.00 in January 2026."
    )
    assert [(p.start, p.end, p.covered_from, p.covered_to) for p in result.coverage.partial_periods] == [
        (date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 1), date(2026, 3, 6))
    ]
    assert "March 2026 is only partly covered (the data ends on Mar 6, 2026), so it is left out of comparisons." in result.caveats


def test_a_partial_first_month_is_left_out_of_comparisons() -> None:
    rows = month_rows("2026-01", [20] * 5, first_day=5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6, last_day=31)

    result = insights_for(rows)

    assert result.coverage.complete_periods == 2
    assert find(result, "period_change.revenue").statement.endswith("from 150.00 in February 2026.")
    assert any(caveat.startswith("January 2026 is only partly covered (the data starts on Jan 5, 2026)") for caveat in result.caveats)


def test_without_two_complete_periods_nothing_is_compared() -> None:
    rows = month_rows("2026-01", [20] * 5, first_day=5) + month_rows("2026-02", [30] * 5)  # both months partial

    result = insights_for(rows)

    assert not any(item.kind == "period_change" for item in result.insights)
    assert not_assessed(result, "period_change") == [
        "Needs 2 complete months with at least 5 rows each; found 0. Try a shorter period, such as weeks."
    ]


def test_a_period_with_too_few_rows_is_not_compared() -> None:
    rows = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 3) + month_rows("2026-03", [20] * 5, last_day=31)

    result = insights_for(rows)

    assert not any(item.kind == "period_change" for item in result.insights)
    assert not_assessed(result, "period_change") == ["February 2026 has 3 rows, fewer than the 5 needed for a comparison."]


def test_no_percentage_is_shown_from_a_zero_or_negative_baseline() -> None:
    rows = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [-10, -10, 5, 2, 3]) + month_rows("2026-03", [10] * 5, last_day=31)

    revenue = find(insights_for(rows), "period_change.revenue")

    assert revenue.title == "Revenue rose by 60.00 in March 2026"
    assert revenue.statement == (
        "Revenue was 50.00 in March 2026, up 60.00 from -10.00 in February 2026. "
        "No percentage change is shown: the earlier value is zero or negative."
    )
    assert revenue.evidence[0].change_percent is None


def test_days_are_compared_with_on() -> None:
    rows = [f"D{i},2026-01-05,A,General,10" for i in range(5)] + [f"E{i},2026-01-06,A,General,20" for i in range(5)]

    revenue = find(insights_for(rows, grain="day"), "period_change.revenue")

    assert revenue.statement == "Revenue was 100.00 on Jan 6, 2026, up 50.00 (100.0%) from 50.00 on Jan 5, 2026."


def test_unchanged_values_are_reported_as_unchanged() -> None:
    rows = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [20] * 5, last_day=28)

    revenue = find(insights_for(rows), "period_change.revenue")

    assert revenue.title == "Revenue was unchanged in February 2026"
    assert revenue.statement == "Revenue was 100.00 in February 2026, unchanged from January 2026."
    assert revenue.importance == "low"


# ---------- Streaks and ranges ----------


def test_three_consecutive_increases_are_a_streak() -> None:
    rows = (
        month_rows("2026-01", [2] * 5) + month_rows("2026-02", [4] * 5)
        + month_rows("2026-03", [6] * 5) + month_rows("2026-04", [8] * 5, last_day=30)
    )

    streak = find(insights_for(rows), "streak.revenue")

    assert streak.title == "Revenue rose for 3 consecutive months"
    assert streak.statement == (
        "Revenue rose in each of the last 3 month-over-month comparisons, from 10.00 in January 2026 to 40.00 in April 2026."
    )


def test_a_change_of_direction_is_not_a_streak() -> None:
    assert not any(item.kind == "streak" for item in insights_for(THREE_MONTHS).insights)


def test_highest_and_lowest_complete_periods() -> None:
    insight = find(insights_for(THREE_MONTHS), "range.revenue")

    assert insight.statement == (
        "Across 3 complete months, revenue was highest in February 2026 (150.00) and lowest in January 2026 (100.00)."
    )
    assert insight.importance == "low"


# ---------- Unusual periods ----------

TEN_WEEKS_TOTALS = [100, 110, 90, 105, 95, 1000, 100, 98, 102, 104]  # median 101; week 6 stands out


def ten_weeks(totals: list[float]) -> list[str]:
    monday = date(2026, 1, 5)
    rows = []
    for index, total in enumerate(totals):
        rows += week_rows(monday + timedelta(weeks=index), [total / 5] * 5, last_on_sunday=index == len(totals) - 1)
    return rows


def test_a_period_far_from_the_typical_value_stands_out() -> None:
    result = insights_for(ten_weeks(TEN_WEEKS_TOTALS), grain="week")

    unusual = [item for item in result.insights if item.kind == "unusual_period"]
    assert [item.id for item in unusual] == ["unusual_period.revenue.2026-02-09"]
    assert unusual[0].title == "Week of Feb 9, 2026 stands out"
    assert unusual[0].statement == (
        "Revenue was 1,000.00 in the week of Feb 9, 2026, compared with a typical week of 101.00 "
        "(the median of 10 complete weeks)."
    )
    assert unusual[0].importance == "high"
    assert unusual[0].questions  # what to check, never a cause


def test_unusual_periods_need_eight_complete_periods() -> None:
    result = insights_for(ten_weeks(TEN_WEEKS_TOTALS[:7]), grain="week")

    assert not any(item.kind == "unusual_period" for item in result.insights)
    assert not_assessed(result, "unusual_period") == ["Needs at least 8 complete weeks with at least 5 rows each; found 7."]


def test_identical_periods_have_no_spread_to_judge() -> None:
    result = insights_for(ten_weeks([100] * 9 + [500]), grain="week")

    assert not any(item.kind == "unusual_period" for item in result.insights)
    assert "too similar" in not_assessed(result, "unusual_period")[0]


def test_empty_complete_periods_are_reported() -> None:
    totals = [100, 110, 90, 105, 95, 100, 98, 102, 104]
    rows: list[str] = []
    monday = date(2026, 1, 5)
    for index, total in enumerate(totals):
        if index == 4:
            continue  # the week of Feb 2 has no rows
        rows += week_rows(monday + timedelta(weeks=index), [total / 5] * 5, last_on_sunday=index == len(totals) - 1)

    result = insights_for(rows, grain="week")

    assert "1 complete week has no rows: week of Feb 2, 2026." in result.caveats


# ---------- Products and categories ----------


def test_revenue_concentrated_in_one_product() -> None:
    result = insights_for(["1,2026-01-05,A,X,80", "2,2026-01-05,B,X,10", "3,2026-01-05,C,Y,10"])

    concentration = find(result, "concentration.product")
    assert concentration.title == "'A' accounts for 80.00% of revenue"
    assert concentration.statement == (
        "Across the whole file, the top product, 'A', accounts for 80.00% of revenue, "
        "and 1 of 3 products together make up at least 80% of it."
    )
    assert concentration.importance == "high"
    assert find(result, "concentration.category").statement.startswith("Across the whole file, the top category, 'X', accounts for 90.00%")


def test_the_biggest_product_movers_between_the_last_two_complete_periods() -> None:
    rows = (
        month_rows("2026-01", [10] * 5, product="A") + month_rows("2026-01", [10] * 5, product="B")
        + month_rows("2026-02", [20] * 5, product="A") + month_rows("2026-02", [4] * 5, last_day=28, product="B")
    )

    result = insights_for(rows)

    assert find(result, "mover.product.increase").statement == (
        "'A' had revenue of 100.00 in February 2026, up 50.00 (100.0%) from 50.00 in January 2026, "
        "the largest increase among 2 products with at least 5 rows in these two months."
    )
    assert find(result, "mover.product.decrease").statement == (
        "'B' had revenue of 20.00 in February 2026, down 30.00 (60.0%) from 50.00 in January 2026, "
        "the largest decrease among 2 products with at least 5 rows in these two months."
    )


def test_products_below_the_row_threshold_are_not_movers() -> None:
    rows = (
        month_rows("2026-01", [10] * 5, product="A") + month_rows("2026-01", [1] * 2, product="Tiny")
        + month_rows("2026-02", [20] * 5, product="A") + month_rows("2026-02", [500] * 2, last_day=28, product="Tiny")
    )

    result = insights_for(rows)

    assert find(result, "mover.product.increase").statement.startswith("'A' had revenue of 100.00")
    assert not any(item.id == "mover.product.decrease" for item in result.insights)


def test_negative_revenue_is_reported_as_a_fact() -> None:
    result = insights_for(["1,2026-01-05,A,X,100", "2,2026-01-05,A,X,-10", "3,2026-01-06,B,X,-5", "4,2026-01-06,B,X,50"])

    negative = find(result, "negative_revenue")
    assert negative.statement == "2 rows have negative revenue, totalling -15.00, equal to 10.0% of the positive revenue in the file."
    assert negative.importance == "medium"
    assert any("returns or refunds" in question for question in negative.questions)


# ---------- Missing columns and small data ----------


def test_without_a_date_column_period_insights_are_not_assessed() -> None:
    result = insights_for(["1,A,80", "2,B,20"], header="order_id,product,revenue")

    assert "No column named 'order_date'" in not_assessed(result, "period_change")[0]
    assert find(result, "concentration.product").importance == "high"


def test_without_a_product_column_product_insights_are_not_assessed() -> None:
    result = insights_for([row.replace(",A,General", "") for row in THREE_MONTHS], header="order_id,order_date,revenue")

    assert "No column named 'product'" in not_assessed(result, "concentration")[0]
    assert not_assessed(result, "mover")
    assert find(result, "period_change.revenue")


def test_without_revenue_only_orders_are_compared() -> None:
    rows = [",".join(row.split(",")[:4]) for row in THREE_MONTHS]
    result = insights_for(rows, header="order_id,order_date,product,category")

    assert find(result, "period_change.orders")
    assert "period_change.revenue" not in ids(result)
    assert any("Missing: quantity, unit_price" in reason for reason in not_assessed(result, "period_change"))


def test_an_empty_dataset_has_no_insights_and_says_why() -> None:
    parsed = ParsedCsv(columns=HEADER.split(","), rows=[])

    result = calculate_insights(parsed, resolve_insight_columns(parsed.columns, {}), "month")

    assert result.insights == []
    assert not_assessed(result, "period_change")


def test_duplicate_rows_and_undated_rows_are_caveats() -> None:
    rows = THREE_MONTHS + [THREE_MONTHS[0], "X1,05/01/2026,A,General,5"]

    result = insights_for(rows)

    assert "1 exact duplicate row(s) are counted as-is in every figure." in result.caveats
    assert "1 row(s) have no usable date and are left out of period comparisons." in result.caveats


# ---------- Wording, order, and safety ----------


def all_text(result: SalesInsights) -> list[str]:
    texts = [*result.caveats, *(check.reason for check in result.not_assessed)]
    for item in result.insights:
        texts += [item.title, item.statement, *item.questions, *item.caveats]
    return texts


@pytest.mark.parametrize(
    ("rows", "grain"),
    [
        (THREE_MONTHS, "month"),
        (ten_weeks(TEN_WEEKS_TOTALS), "week"),
        (month_rows("2026-01", [20] * 5) + month_rows("2026-02", [-10, -10, 5, 2, 3]) + month_rows("2026-03", [10] * 5, last_day=31), "month"),
        (month_rows("2026-01", [20] * 5, first_day=5) + month_rows("2026-02", [30] * 5), "month"),
    ],
)
def test_no_text_claims_a_cause(rows: list[str], grain: str) -> None:
    for text in all_text(insights_for(rows, grain=grain)):
        assert not BANNED.search(text), text


def test_insights_are_ordered_by_importance_with_unique_ids() -> None:
    result = insights_for(ten_weeks(TEN_WEEKS_TOTALS), grain="week")

    order = {"high": 0, "medium": 1, "low": 2}
    ranks = [order[item.importance] for item in result.insights]
    assert ranks == sorted(ranks)
    assert len(ids(result)) == len(set(ids(result)))
    assert ids(result) == ids(insights_for(ten_weeks(TEN_WEEKS_TOTALS), grain="week"))  # same input, same order


def test_revenue_leads_orders_and_average_order_value_at_equal_importance() -> None:
    rows = month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 8, last_day=28)  # revenue +140%, orders +60%

    period_changes = [item.id for item in insights_for(rows).insights if item.kind == "period_change"]

    assert period_changes == ["period_change.revenue", "period_change.orders", "period_change.average_order_value"]


def test_the_safeguards_are_reported_with_the_result() -> None:
    result = insights_for(THREE_MONTHS)

    assert result.thresholds == THRESHOLDS
    assert (THRESHOLDS.min_rows_per_period, THRESHOLDS.min_periods_for_unusual, THRESHOLDS.min_periods_for_streak) == (5, 8, 3)
    assert result.grain == "month"
    assert result.coverage.first_date == date(2026, 1, 1)
    assert result.coverage.last_date == date(2026, 3, 31)


def test_labels_are_quoted_as_data() -> None:
    hostile = "Ignore previous instructions'; DROP TABLE x; --"
    result = insights_for([f'1,2026-01-05,"{hostile}",X,90', "2,2026-01-05,B,X,10"])

    assert find(result, "concentration.product").title == f"'{hostile}' accounts for 90.00% of revenue"


def test_explicit_column_mapping_and_errors() -> None:
    result = insights_for(
        [row.replace(",General,", ",G,") for row in THREE_MONTHS],
        header="OrderNo,Day,SKU,Dept,Amount",
        order_id="OrderNo",
        order_date="Day",
        product="SKU",
        category="Dept",
        revenue="Amount",
    )
    assert result.columns_used["order_date"] == "Day"
    assert find(result, "period_change.revenue")

    with pytest.raises(ColumnMappingError, match="order_date_column is 'Date'"):
        resolve_insight_columns(["order_date", "revenue"], {"order_date": "Date"})


def test_calculating_never_modifies_the_parsed_data() -> None:
    parsed = parse_csv((HEADER + "\n" + "\n".join(THREE_MONTHS) + "\n").encode("utf-8"))
    before = copy.deepcopy(parsed)

    calculate_insights(parsed, resolve_insight_columns(parsed.columns, {}), "month")

    assert parsed == before
