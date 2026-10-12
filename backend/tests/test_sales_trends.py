"""Unit tests for DuckDB sales trends: grouping by period, date rules, and exact per-period values."""

import copy
from datetime import date
from pathlib import Path

import pytest

from app.analytics.retail_metrics import ColumnMappingError, calculate_retail_metrics, resolve_columns
from app.analytics.sales_trends import (
    MAX_PERIODS,
    SalesTrends,
    calculate_sales_trends,
    resolve_trend_columns,
)
from app.ingestion.csv_parser import ParsedCsv, parse_csv
from app.ingestion.profiler import detect_type

FIXTURES = Path(__file__).parent / "fixtures"


def trends_for(csv_text: str, grain: str = "month", **requested: str) -> SalesTrends:
    parsed = parse_csv(csv_text.encode("utf-8"))
    return calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, requested), grain)


def trends_for_fixture(name: str, grain: str = "month", **requested: str) -> SalesTrends:
    return trends_for((FIXTURES / name).read_text(encoding="utf-8"), grain, **requested)


def starts(trends: SalesTrends) -> list[date]:
    return [period.start for period in trends.periods]


def values(series) -> list[int | float | None]:
    return [point.value for point in series.points]


# ---------- Grouping ----------


def test_month_is_the_default_grain_and_groups_the_sample_into_january() -> None:
    parsed = parse_csv((FIXTURES / "sample_sales.csv").read_bytes())
    t = calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}))

    assert t.grain == "month"
    assert [(p.start, p.end, p.row_count) for p in t.periods] == [(date(2026, 1, 1), date(2026, 1, 31), 5)]
    assert values(t.revenue) == [140.95]
    assert values(t.order_count) == [5]
    assert values(t.average_order_value) == [28.19]


def test_daily_grouping_gives_one_period_per_date() -> None:
    t = trends_for_fixture("sample_sales.csv", grain="day")

    assert [(p.start, p.end) for p in t.periods] == [
        (date(2026, 1, 5), date(2026, 1, 5)),
        (date(2026, 1, 6), date(2026, 1, 6)),
        (date(2026, 1, 7), date(2026, 1, 7)),
    ]
    assert values(t.revenue) == [58.25, 12.0, 70.7]  # 37.00 + 21.25 | 12.00 | 55.50 + 15.20
    assert values(t.order_count) == [2, 1, 2]
    assert values(t.average_order_value) == [29.125, 12.0, 35.35]
    assert [p.rows_included for p in t.revenue.points] == [2, 1, 2]


def test_weekly_grouping_uses_iso_weeks_starting_on_monday() -> None:
    # 2026-01-04 is a Sunday, 2026-01-05 a Monday: they belong to different weeks.
    t = trends_for(
        "order_id,order_date,revenue\nA,2026-01-04,10\nB,2026-01-05,20\nC,2026-01-11,5\n",
        grain="week",
    )

    assert [(p.start, p.end) for p in t.periods] == [
        (date(2025, 12, 29), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 11)),
    ]
    assert values(t.revenue) == [10.0, 25.0]
    assert values(t.order_count) == [1, 2]


def test_monthly_periods_end_on_the_last_day_of_the_month() -> None:
    t = trends_for("order_date,revenue\n2024-02-29,1\n2024-04-30,1\n", grain="month")

    assert [(p.start, p.end) for p in t.periods] == [
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 31)),
        (date(2024, 4, 1), date(2024, 4, 30)),
    ]


def test_periods_without_rows_are_listed_with_no_values_never_zero() -> None:
    t = trends_for("order_id,order_date,revenue\nA,2026-01-10,10\nB,2026-03-02,30\n")

    assert starts(t) == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert [p.row_count for p in t.periods] == [1, 0, 1]
    assert values(t.revenue) == [10.0, None, 30.0]
    assert values(t.order_count) == [1, None, 1]
    assert values(t.average_order_value) == [10.0, None, 30.0]
    assert any("1 period(s)" in note and "no rows" in note for note in t.dated_rows.notes)


def test_rows_in_any_order_produce_periods_in_date_order() -> None:
    t = trends_for("order_date,revenue\n2026-03-01,3\n2026-01-01,1\n2026-02-01,2\n")

    assert values(t.revenue) == [1.0, 2.0, 3.0]


def test_period_revenue_adds_up_to_total_revenue_when_every_date_is_usable() -> None:
    parsed = parse_csv((FIXTURES / "sample_sales.csv").read_bytes())
    total = calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {})).total_revenue.value

    t = calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "day")

    assert sum(values(t.revenue)) == pytest.approx(total)
    assert t.revenue.rows_included == 5


# ---------- Revenue: same rules as total_revenue ----------


def test_revenue_column_wins_over_quantity_times_unit_price() -> None:
    t = trends_for("order_date,quantity,unit_price,revenue\n2026-01-05,2,10.00,18.00\n")

    assert values(t.revenue) == [18.0]
    assert t.revenue.columns_used == ["revenue"]
    assert "as recorded" in t.revenue.definition


def test_quantity_times_unit_price_is_labelled_gross_sales() -> None:
    t = trends_for_fixture("sample_sales.csv")

    assert t.revenue.columns_used == ["quantity", "unit_price"]
    assert "gross sales" in t.revenue.definition


def test_decimal_math_is_exact_within_a_period() -> None:
    t = trends_for("order_date,revenue\n2026-01-01,0.1\n2026-01-02,0.2\n")

    assert values(t.revenue) == [0.3]


def test_negative_revenue_is_included_as_is_and_flagged() -> None:
    t = trends_for(
        "order_id,order_date,revenue\nA,2026-01-05,50\nR1,2026-02-03,-20\nR2,2026-02-04,-15\nB,2026-02-05,5\n"
    )

    assert values(t.revenue) == [50.0, -30.0]  # February is a net refund month
    assert values(t.average_order_value) == [50.0, -10.0]
    assert any("2 row(s) have negative values" in note for note in t.revenue.notes)


def test_dated_rows_with_unusable_revenue_are_excluded_with_line_numbers() -> None:
    t = trends_for("order_id,order_date,revenue\nA,2026-01-05,10\nB,2026-01-06,N/A\nC,2026-01-07,\n")

    assert values(t.revenue) == [10.0]
    assert t.revenue.points[0].rows_included == 1
    assert t.revenue.rows_excluded == 2
    assert any("(lines 3, 4)" in note for note in t.revenue.notes)
    assert values(t.order_count) == [3]  # order IDs do not depend on revenue


def test_period_with_rows_but_no_usable_revenue_has_no_revenue_value() -> None:
    t = trends_for("order_date,revenue\n2026-01-05,10\n2026-02-05,N/A\n")

    assert [p.row_count for p in t.periods] == [1, 1]
    assert values(t.revenue) == [10.0, None]
    assert [p.rows_included for p in t.revenue.points] == [1, 0]


# ---------- Orders and average order value ----------


def test_order_spanning_rows_in_one_period_is_counted_once() -> None:
    t = trends_for("order_id,order_date,revenue\nA1,2026-01-05,18\nA1,2026-01-05,5.5\nA2,2026-01-06,12\n")

    assert values(t.order_count) == [2]
    assert values(t.average_order_value) == [17.75]  # 35.50 / 2


def test_order_with_rows_in_two_periods_is_counted_in_each_and_flagged() -> None:
    t = trends_for("order_id,order_date,revenue\nA1,2026-01-31,10\nA1,2026-02-01,4\nB,2026-02-02,6\n")

    assert values(t.order_count) == [1, 2]
    assert any("1 order(s)" in note and "more than one period" in note for note in t.order_count.notes)


def test_blank_order_ids_are_excluded_from_orders_but_not_from_revenue() -> None:
    t = trends_for("order_id,order_date,revenue\nA,2026-01-05,10\n ,2026-01-06,4\n")

    assert values(t.revenue) == [14.0]
    assert values(t.order_count) == [1]
    assert values(t.average_order_value) == [10.0]  # only rows with both an order ID and revenue
    assert any("blank order ID" in note and "(lines 3)" in note for note in t.order_count.notes)


def test_without_order_ids_only_revenue_is_calculated() -> None:
    t = trends_for("order_date,revenue\n2026-01-05,10\n")

    assert t.revenue.status == "calculated"
    assert t.order_count.status == "unavailable"
    assert t.order_count.points == []
    assert "order_id_column" in t.order_count.notes[0]
    assert t.average_order_value.status == "unavailable"


def test_without_revenue_columns_orders_are_still_calculated() -> None:
    t = trends_for("order_id,order_date,quantity\nA,2026-01-05,2\n")

    assert t.revenue.status == "unavailable"
    assert "Missing: unit_price" in t.revenue.notes[0]
    assert values(t.order_count) == [1]
    assert t.average_order_value.status == "unavailable"


# ---------- Dates: the profiler's rule, exactly ----------


@pytest.mark.parametrize(
    "text",
    [
        "2026-01-05",
        " 2026-01-05 ",
        "2024-02-29",
        "2025-02-29",
        "2026-02-30",
        "2026-13-01",
        "2026-00-10",
        "0000-01-01",
        "0001-01-01",
        "9999-12-31",
        "2026-1-5",
        "05/01/2026",
        "2026/01/05",
        "20260105",
        "2026-01-05 10:00",
        "2026-01-05T10:00:00",
        "N/A",
    ],
)
def test_usable_dates_match_the_profiler_date_rule(text: str) -> None:
    t = trends_for(f"order_date,revenue\n{text},1\n")

    assert (t.dated_rows.value == 1) == (detect_type(text) == "date")


def test_invalid_dates_are_excluded_and_reported_with_line_numbers() -> None:
    t = trends_for_fixture("messy_sales.csv")  # line 6 has the impossible date 2026-02-30

    assert t.dated_rows.value == 5
    assert t.dated_rows.rows_excluded == 1
    assert any("(lines 6)" in note for note in t.dated_rows.notes)
    assert sum(p.row_count for p in t.periods) == 5


def test_mixed_date_formats_only_use_yyyy_mm_dd() -> None:
    t = trends_for(
        "order_id,order_date,revenue\n"
        "A,2026-01-05,10\n"  # line 2: usable
        "B,05/01/2026,20\n"  # line 3: other format
        "C,,30\n"  # line 4: blank
        "D,2026-01-06 09:30,40\n"  # line 5: has a time
        "E, 2026-02-01 ,50\n"  # line 6: usable (spaces ignored)
    )

    assert starts(t) == [date(2026, 1, 1), date(2026, 2, 1)]
    assert values(t.revenue) == [10.0, 50.0]
    assert t.dated_rows.rows_included == 2
    assert t.dated_rows.rows_excluded == 3
    assert any("(lines 3, 4, 5)" in note for note in t.dated_rows.notes)
    assert t.revenue.rows_excluded == 3  # undated rows are excluded from every series


def test_no_usable_dates_makes_the_trend_unavailable() -> None:
    t = trends_for("order_id,order_date,revenue\nA,05/01/2026,10\nB,,20\n")

    assert t.dated_rows.status == "unavailable"
    assert t.periods == []
    for series in (t.revenue, t.order_count, t.average_order_value):
        assert series.status == "unavailable"
        assert series.points == []
    assert "YYYY-MM-DD" in t.dated_rows.notes[0]


def test_a_dataset_without_rows_has_no_periods() -> None:
    parsed = ParsedCsv(columns=["order_id", "order_date", "revenue"], rows=[])

    t = calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "month")

    assert t.periods == []
    assert t.dated_rows.status == "unavailable"
    assert t.revenue.status == "unavailable"


def test_without_a_date_column_nothing_is_grouped() -> None:
    t = trends_for_fixture("order_lines.csv")

    assert t.columns_used["order_date"] is None
    assert t.dated_rows.status == "unavailable"
    assert "order_date_column" in t.dated_rows.notes[0]
    assert t.periods == []
    assert t.revenue.status == "unavailable"


def test_too_many_periods_is_unavailable_and_suggests_a_coarser_grain() -> None:
    # Roughly 5,800 days: too many for daily periods, but fine by month.
    csv_text = "order_date,revenue\n2010-01-01,1\n2025-12-31,1\n"

    daily = trends_for(csv_text, grain="day")
    monthly = trends_for(csv_text, grain="month")

    assert daily.periods == []
    assert daily.revenue.status == "unavailable"
    assert str(MAX_PERIODS) in daily.dated_rows.notes[0]
    assert "2010-01-01" in daily.dated_rows.notes[0] and "2025-12-31" in daily.dated_rows.notes[0]
    assert len(monthly.periods) == 192


def test_the_last_week_of_the_calendar_ends_on_the_last_representable_day() -> None:
    t = trends_for("order_date,revenue\n9999-12-31,1\n", grain="week")

    assert [(p.start, p.end) for p in t.periods] == [(date(9999, 12, 27), date(9999, 12, 31))]


# ---------- Safety ----------


def test_revenue_too_large_to_total_is_unavailable_but_orders_still_count() -> None:
    big = "9" * 30  # the largest whole number DECIMAL(38, 8) holds; two of them overflow
    t = trends_for(f"order_id,order_date,revenue\nA,2026-01-05,{big}\nB,2026-01-06,{big}\n")

    assert t.revenue.status == "unavailable"
    assert "too large" in t.revenue.notes[0]
    assert t.average_order_value.status == "unavailable"
    assert values(t.order_count) == [2]


def test_quantity_times_price_too_large_for_one_row_is_unavailable() -> None:
    t = trends_for(f"order_date,quantity,unit_price\n2026-01-05,{'9' * 20},{'9' * 20}\n")

    assert t.revenue.status == "unavailable"
    assert "too large" in t.revenue.notes[0]
    assert [p.row_count for p in t.periods] == [1]


def test_hostile_column_names_are_handled_safely() -> None:
    hostile = 'day"); DROP TABLE uploaded_rows; --'
    t = trends_for(f'"{hostile.replace(chr(34), chr(34) * 2)}",revenue\n2026-01-05,3.00\n', order_date=hostile)

    assert values(t.revenue) == [3.0]


def test_calculating_trends_never_modifies_the_parsed_data() -> None:
    parsed = parse_csv(b"order_id,order_date,revenue\nA1, 2026-01-05 ,3.00\nA2,N/A,\n")
    before = copy.deepcopy(parsed)

    calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "week")

    assert parsed == before


def test_an_unknown_grain_is_rejected() -> None:
    parsed = parse_csv(b"order_date,revenue\n2026-01-05,1\n")

    with pytest.raises(ValueError, match="grain must be one of day, week, month"):
        calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "year")  # type: ignore[arg-type]


# ---------- Column mapping: exact names or explicit choices, never guesses ----------


def test_explicit_column_mapping_for_every_role() -> None:
    t = trends_for(
        "Day,OrderNo,Qty,Price\n2026-01-05,X1,2,3.00\n2026-01-05,X2,1,4.00\n",
        grain="day",
        order_date="Day",
        order_id="OrderNo",
        quantity="Qty",
        unit_price="Price",
    )

    assert t.columns_used == {
        "order_date": "Day",
        "order_id": "OrderNo",
        "quantity": "Qty",
        "unit_price": "Price",
        "revenue": None,
    }
    assert values(t.revenue) == [10.0]
    assert values(t.order_count) == [2]


def test_similar_date_column_names_are_not_guessed() -> None:
    t = trends_for("Order Date,date,revenue\n2026-01-05,2026-01-05,1\n")

    assert t.columns_used["order_date"] is None
    assert t.periods == []


def test_mapping_to_a_missing_column_is_an_error() -> None:
    with pytest.raises(ColumnMappingError, match="order_date_column is 'Date'"):
        resolve_trend_columns(["order_date", "revenue"], {"order_date": "Date"})


def test_one_column_cannot_fill_two_roles() -> None:
    with pytest.raises(ColumnMappingError, match="more than one role"):
        resolve_trend_columns(["order_date", "revenue"], {"order_id": "order_date"})


def test_metrics_column_resolution_is_unchanged_by_the_date_role() -> None:
    # The metrics roles stay exactly as they were; order_date is a trends-only role.
    assert resolve_columns(["order_date", "revenue"], {}) == {
        "order_id": None,
        "quantity": None,
        "unit_price": None,
        "revenue": "revenue",
    }
