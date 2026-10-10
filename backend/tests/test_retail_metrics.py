"""Unit tests for DuckDB retail metrics: which metrics are available, and exact values."""

import copy
from pathlib import Path

import pytest

from app.analytics.retail_metrics import (
    ColumnMappingError,
    RetailMetrics,
    calculate_retail_metrics,
    resolve_columns,
)
from app.ingestion.csv_parser import ParsedCsv, parse_csv

FIXTURES = Path(__file__).parent / "fixtures"


def metrics_for(csv_text: str, **requested: str) -> RetailMetrics:
    parsed = parse_csv(csv_text.encode("utf-8"))
    return calculate_retail_metrics(parsed, resolve_columns(parsed.columns, requested))


def metrics_for_fixture(name: str, **requested: str) -> RetailMetrics:
    return metrics_for((FIXTURES / name).read_text(encoding="utf-8"), **requested)


# ---------- Calculated values ----------


def test_sample_sales_metrics_from_quantity_and_unit_price() -> None:
    m = metrics_for_fixture("sample_sales.csv")

    assert m.row_count.value == 5
    assert m.total_quantity.value == 15
    assert m.total_revenue.value == 140.95  # 37.00 + 21.25 + 12.00 + 55.50 + 15.20
    assert m.total_revenue.columns_used == ["quantity", "unit_price"]
    assert m.order_count.value == 5
    assert m.average_order_value.value == 28.19


def test_revenue_column_is_used_when_present_and_orders_span_rows() -> None:
    m = metrics_for_fixture("order_lines.csv")

    # The revenue column records a discount on line 2 (18.00, not 2 x 10.00), so it must win.
    assert m.total_revenue.value == 48.0
    assert m.total_revenue.columns_used == ["revenue"]
    assert m.total_quantity.value == 7
    assert m.order_count.value == 3  # A1 spans two rows
    assert m.average_order_value.value == 16.0


def test_explicit_column_mapping() -> None:
    m = metrics_for(
        "OrderNo,Qty,Price\nX1,2,3.00\nX2,1,4.00\n",
        order_id="OrderNo",
        quantity="Qty",
        unit_price="Price",
    )

    assert m.columns_used == {"order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price", "revenue": None}
    assert m.total_revenue.value == 10.0


# ---------- Missing columns: report, never guess ----------


def test_file_without_sales_columns_only_has_row_count() -> None:
    m = metrics_for_fixture("no_sales_columns.csv")

    assert m.row_count.status == "calculated"
    for metric in (m.total_quantity, m.total_revenue, m.order_count, m.average_order_value):
        assert metric.status == "unavailable"
        assert metric.value is None
        assert metric.notes  # a reason is always given
    assert "quantity_column" in m.total_quantity.notes[0]
    assert "Missing: quantity, unit_price" in m.total_revenue.notes[0]


def test_similar_column_names_are_not_guessed() -> None:
    m = metrics_for("Quantity,Unit Price\n2,3.00\n")

    assert m.columns_used["quantity"] is None
    assert m.total_quantity.status == "unavailable"


def test_average_order_value_needs_an_order_id() -> None:
    m = metrics_for("quantity,unit_price\n2,3.00\n")

    assert m.total_revenue.status == "calculated"
    assert m.average_order_value.status == "unavailable"
    assert "order ID" in m.average_order_value.notes[0]


def test_unknown_mapped_column_is_an_error() -> None:
    with pytest.raises(ColumnMappingError, match="no column with that exact name. Available columns: a, b"):
        resolve_columns(["a", "b"], {"quantity": "Qty"})


def test_one_column_cannot_fill_two_roles() -> None:
    with pytest.raises(ColumnMappingError, match="more than one role"):
        resolve_columns(["amount"], {"quantity": "amount", "revenue": "amount"})


def test_blank_mapping_means_not_provided() -> None:
    assert resolve_columns(["quantity"], {"quantity": "  "})["quantity"] == "quantity"


# ---------- Numeric edge cases ----------


def test_numeric_edge_cases_are_excluded_and_reported() -> None:
    m = metrics_for_fixture("numeric_edge_cases.csv")

    quantity = m.total_quantity
    assert quantity.value == 9  # 2 + 3 - 1 + 1 + 4; blank, N/A, 1,000 and 1e3 excluded
    assert (quantity.rows_included, quantity.rows_excluded) == (5, 4)
    assert "(lines 5, 6, 8, 9)" in quantity.notes[0]
    assert "negative" in quantity.notes[1]

    revenue = m.total_revenue
    assert revenue.value == 0.7  # 0.20 + 0.60 - 0.10; $5.00 and 0.123456789 also excluded
    assert (revenue.rows_included, revenue.rows_excluded) == (3, 6)
    assert "(lines 5, 6, 7, 8, 9, ...)" in revenue.notes[0]


def test_decimal_math_is_exact() -> None:
    m = metrics_for("quantity,unit_price\n1,0.1\n1,0.2\n")

    assert m.total_revenue.value == 0.3  # floating point would give 0.30000000000000004


def test_all_values_unusable_means_unavailable_not_zero() -> None:
    m = metrics_for("quantity\nN/A\n\nmany\n")

    assert m.total_quantity.status == "unavailable"
    assert m.total_quantity.value is None


def test_values_too_large_are_reported_not_crashing() -> None:
    huge = "9" * 30
    m = metrics_for(f"quantity,unit_price\n{huge},{huge}\n")

    assert m.total_revenue.status == "unavailable"
    assert "too large" in m.total_revenue.notes[0]


def test_number_beyond_decimal_range_is_excluded() -> None:
    m = metrics_for(f"quantity\n{'1' * 31}\n5\n")

    assert m.total_quantity.value == 5
    assert m.total_quantity.rows_excluded == 1


def test_blank_order_ids_are_excluded_from_order_count() -> None:
    m = metrics_for("order_id,quantity\nA1,1\n,2\n  ,3\nA1,4\n")

    assert m.order_count.value == 1
    assert m.order_count.rows_excluded == 2
    assert "(lines 3, 4)" in m.order_count.notes[0]


# ---------- Safety ----------


def test_duplicate_rows_are_counted_as_is_and_flagged() -> None:
    m = metrics_for_fixture("messy_sales.csv")

    assert m.row_count.value == 6
    assert "1 exact duplicate row(s)" in m.row_count.notes[0]


def test_hostile_column_name_is_handled_safely() -> None:
    hostile = 'qty"); DROP TABLE uploaded_rows; --'
    m = metrics_for(f'"{hostile.replace(chr(34), chr(34) * 2)}",unit_price\n2,3.00\n', quantity=hostile)

    assert m.total_quantity.value == 2
    assert m.total_revenue.value == 6.0


def test_empty_dataset_does_not_crash() -> None:
    parsed = ParsedCsv(columns=["order_id", "quantity", "unit_price"], rows=[])

    m = calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {}))

    assert m.row_count.value == 0
    assert m.total_quantity.status == "unavailable"
    assert m.average_order_value.status == "unavailable"


def test_calculating_metrics_never_modifies_the_parsed_data() -> None:
    parsed = parse_csv(b"order_id,quantity,unit_price\nA1, 2 ,3.00\nA2,N/A,\n")
    before = copy.deepcopy(parsed)

    calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {}))

    assert parsed == before
