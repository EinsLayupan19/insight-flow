"""Unit tests for product and category performance: labels, ranking, overflow, and exact values.

catalog_sales.csv, by line:
  2  A1 Coffee Beans / Beverages   2 x 18.50 =  37.00
  3  A1 Ceramic Mug  / Homeware    1 x 12.00 =  12.00
  4  A2 Green Tea    / Beverages   5 x  4.25 =  21.25
  5  A3 green tea    / Beverages   1 x  4.25 =   4.25   (differs from line 4 only by case)
  6  A4 " Oat Milk " / Dairy       4 x  3.80 =  15.20   (spaces around the label)
  7  A5 Oat Milk     / Beverages   2 x  3.80 =   7.60   (a second category for Oat Milk)
  8  A6 (blank)      / Homeware    1 x  9.99 =   9.99
  9  A7 Ceramic Mug  / (blank)     2 x 12.00 =  24.00
 10  R1 Coffee Beans / Beverages  -1 x 18.50 = -18.50   (a refund)
"""

import copy
from pathlib import Path

import pytest

from app.analytics.product_performance import (
    MAX_GROUPS,
    Breakdown,
    PerformanceGroup,
    ProductPerformance,
    calculate_product_performance,
    resolve_performance_columns,
)
from app.analytics.retail_metrics import ColumnMappingError, calculate_retail_metrics, resolve_columns
from app.ingestion.csv_parser import ParsedCsv, parse_csv

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = (FIXTURES / "catalog_sales.csv").read_text(encoding="utf-8")


def performance_for(csv_text: str, **requested: str) -> ProductPerformance:
    parsed = parse_csv(csv_text.encode("utf-8"))
    return calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, requested))


def group(breakdown: Breakdown, label: str) -> PerformanceGroup:
    return next(item for item in breakdown.groups if item.label == label)


def labels(breakdown: Breakdown) -> list[str]:
    return [item.label for item in breakdown.groups]


# ---------- Products ----------


def test_products_are_ranked_by_revenue_with_exact_values() -> None:
    products = performance_for(CATALOG).products

    assert products.status == "calculated"
    assert products.ranked_by == "revenue"
    assert labels(products) == ["Ceramic Mug", "Oat Milk", "Green Tea", "Coffee Beans", "green tea"]
    mug = group(products, "Ceramic Mug")
    assert (mug.revenue, mug.quantity, mug.order_count, mug.row_count) == (36.0, 3.0, 2, 2)
    assert group(products, "Coffee Beans").revenue == 18.5  # 37.00 - 18.50: the refund is included as-is
    assert products.group_count == 5
    assert products.remaining is None


def test_surrounding_spaces_are_trimmed_so_one_product_is_one_group() -> None:
    oat = group(performance_for(CATALOG).products, "Oat Milk")

    assert oat.row_count == 2  # " Oat Milk " (line 6) and "Oat Milk" (line 7)
    assert oat.revenue == 22.8


def test_revenue_share_is_a_percentage_of_the_labelled_revenue() -> None:
    products = performance_for(CATALOG).products

    assert products.revenue.value == 102.8  # all rows with a product label and usable revenue
    assert [item.revenue_share for item in products.groups] == [35.02, 22.18, 20.67, 18.0, 4.13]


def test_product_revenue_adds_up_to_total_revenue_when_every_row_has_a_product() -> None:
    parsed = parse_csv((FIXTURES / "sample_sales.csv").read_bytes())
    total = calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {})).total_revenue.value

    products = calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, {})).products

    assert products.revenue.value == pytest.approx(total)
    assert sum(item.revenue for item in products.groups) == pytest.approx(total)


def test_orders_are_counted_per_product_and_the_overlap_is_explained() -> None:
    products = performance_for(CATALOG).products

    assert products.order_count.value == 7  # distinct orders among rows with a product
    assert sum(item.order_count for item in products.groups) == 8  # A1 holds two products
    assert any("counted under each" in note for note in products.order_count.notes)


def test_each_product_lists_its_categories() -> None:
    products = performance_for(CATALOG).products

    assert group(products, "Oat Milk").categories == ["Beverages", "Dairy"]
    assert group(products, "Ceramic Mug").categories == ["Homeware"]  # the blank category on line 9 is not listed


# ---------- Categories ----------


def test_categories_are_ranked_with_their_product_counts() -> None:
    categories = performance_for(CATALOG).categories

    assert categories.status == "calculated"
    assert labels(categories) == ["Beverages", "Homeware", "Dairy"]
    beverages = group(categories, "Beverages")
    assert (beverages.revenue, beverages.quantity, beverages.order_count) == (51.6, 9.0, 5)
    assert beverages.product_count == 4  # Coffee Beans, Green Tea, green tea, Oat Milk
    assert group(categories, "Homeware").product_count == 1  # line 8 has no product
    assert categories.revenue.value == 88.79


def test_product_counts_are_empty_without_a_product_column() -> None:
    categories = performance_for("category,revenue\nTea,5\nTea,2\n").categories

    assert group(categories, "Tea").product_count is None
    assert group(categories, "Tea").categories == []


# ---------- Labels: trimmed, never merged, never guessed ----------


def test_blank_labels_are_excluded_and_reported_with_line_numbers() -> None:
    result = performance_for(CATALOG)

    assert result.products.rows_included == 8
    assert result.products.rows_excluded == 1
    assert any("blank product" in note and "(lines 8)" in note for note in result.products.notes)
    assert any("blank category" in note and "(lines 9)" in note for note in result.categories.notes)


def test_labels_differing_only_by_case_or_spacing_are_flagged_not_merged() -> None:
    products = performance_for(CATALOG).products

    assert "Green Tea" in labels(products) and "green tea" in labels(products)
    assert group(products, "Green Tea").similar_labels == ["green tea"]
    assert group(products, "green tea").similar_labels == ["Green Tea"]
    assert group(products, "Ceramic Mug").similar_labels == []
    assert any("letter case or spacing" in note and "'Green Tea'" in note for note in products.notes)


def test_inner_spacing_differences_are_flagged() -> None:
    products = performance_for("product,revenue\nGreen  Tea,1\nGreen Tea,2\n").products

    assert labels(products) == ["Green Tea", "Green  Tea"]
    assert group(products, "Green  Tea").similar_labels == ["Green Tea"]


def test_products_in_more_than_one_category_are_flagged() -> None:
    products = performance_for(CATALOG).products

    assert any("1 product(s)" in note and "more than one category" in note and "'Oat Milk'" in note for note in products.notes)


# ---------- Ranking ----------


def test_ties_are_broken_by_label_in_a_fixed_text_order() -> None:
    products = performance_for("product,revenue\nb,10\nB,10\na,10\nc,20\n").products

    assert labels(products) == ["c", "B", "a", "b"]  # uppercase sorts before lowercase


def test_products_without_usable_revenue_are_ranked_last() -> None:
    products = performance_for("product,revenue\nTea,N/A\nMug,-5\nBeans,3\n").products

    assert labels(products) == ["Beans", "Mug", "Tea"]
    assert group(products, "Tea").revenue is None
    assert group(products, "Tea").revenue_share is None
    assert any("(lines 2)" in note for note in products.revenue.notes)


def test_without_revenue_products_are_ranked_by_quantity() -> None:
    products = performance_for("product,quantity\nTea,1\nMug,4\nBeans,2\n").products

    assert products.ranked_by == "quantity"
    assert labels(products) == ["Mug", "Beans", "Tea"]
    assert products.revenue.status == "unavailable"
    assert "Missing: unit_price" in products.revenue.notes[0]
    assert all(item.revenue is None and item.revenue_share is None for item in products.groups)


def test_without_revenue_or_quantity_products_are_ranked_by_rows() -> None:
    products = performance_for("product\nTea\nMug\nMug\n").products

    assert products.ranked_by == "row_count"
    assert labels(products) == ["Mug", "Tea"]


# ---------- Negative revenue and shares ----------


def test_negative_revenue_is_included_and_flagged() -> None:
    products = performance_for(CATALOG).products

    assert any("1 row(s) have negative values" in note for note in products.revenue.notes)


def test_shares_are_left_empty_when_total_revenue_is_not_positive() -> None:
    products = performance_for("product,revenue\nTea,10\nRefunds,-10\n").products

    assert products.revenue.value == 0.0
    assert [item.revenue_share for item in products.groups] == [None, None]
    assert any("share" in note.lower() and "not positive" in note for note in products.revenue.notes)


# ---------- Missing columns and empty data ----------


def test_without_a_category_column_only_the_category_breakdown_is_unavailable() -> None:
    result = performance_for((FIXTURES / "sample_sales.csv").read_text(encoding="utf-8"))

    assert result.products.status == "calculated"
    assert result.categories.status == "unavailable"
    assert result.categories.groups == []
    assert "No column named 'category'" in result.categories.notes[0]
    assert "category_column" in result.categories.notes[0]
    assert all(item.categories == [] for item in result.products.groups)


def test_without_a_product_column_only_the_product_breakdown_is_unavailable() -> None:
    result = performance_for("category,revenue\nTea,5\n")

    assert result.products.status == "unavailable"
    assert "product_column" in result.products.notes[0]
    assert result.categories.status == "calculated"


def test_every_label_blank_makes_the_breakdown_unavailable() -> None:
    products = performance_for("product,revenue\n ,5\n,3\n").products

    assert products.status == "unavailable"
    assert products.groups == []
    assert "Every row has a blank product" in products.notes[0]
    assert "(lines 2, 3)" in products.notes[0]


def test_a_dataset_without_rows_has_no_groups() -> None:
    parsed = ParsedCsv(columns=["product", "category", "revenue"], rows=[])

    result = calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, {}))

    assert result.products.status == "unavailable"
    assert result.categories.status == "unavailable"
    assert "no data rows" in result.products.notes[0]


def test_measures_are_unavailable_on_their_own_when_their_column_is_missing() -> None:
    products = performance_for("product,revenue\nTea,5\n").products

    assert products.revenue.status == "calculated"
    assert products.quantity.status == "unavailable"
    assert "quantity_column" in products.quantity.notes[0]
    assert products.order_count.status == "unavailable"
    assert "order_id_column" in products.order_count.notes[0]
    assert group(products, "Tea").quantity is None
    assert group(products, "Tea").order_count is None


# ---------- The 1,000-group cap ----------


def test_more_than_1000_groups_lists_the_top_1000_and_summarizes_the_rest() -> None:
    # P0000..P1002 with falling revenue; the last three products have two rows each.
    lines = ["order_id,product,quantity,revenue"]
    for i in range(MAX_GROUPS + 3):
        lines.append(f"O{i},P{i:04d},1,{2000 - i}")
    for i in range(MAX_GROUPS, MAX_GROUPS + 3):
        lines.append(f"X{i},P{i:04d},2,1")
    products = performance_for("\n".join(lines) + "\n").products

    assert products.group_count == MAX_GROUPS + 3
    assert len(products.groups) == MAX_GROUPS
    assert products.groups[-1].label == "P0999"
    assert products.remaining is not None
    assert products.remaining.group_count == 3
    assert products.remaining.row_count == 6
    assert products.remaining.revenue == (1000 + 999 + 998) + 3
    assert products.remaining.quantity == 3 + 6
    assert products.remaining.order_count == 6
    # Listed groups plus the remaining summary account for every labelled row.
    assert sum(item.row_count for item in products.groups) + products.remaining.row_count == products.rows_included
    assert sum(item.revenue for item in products.groups) + products.remaining.revenue == products.revenue.value
    assert any("top 1,000 of 1,003 products" in note for note in products.notes)


def test_exactly_1000_groups_has_no_remaining_summary() -> None:
    lines = ["product,revenue", *(f"P{i:04d},1" for i in range(MAX_GROUPS))]
    products = performance_for("\n".join(lines) + "\n").products

    assert len(products.groups) == MAX_GROUPS
    assert products.remaining is None


# ---------- Column mapping ----------


def test_explicit_column_mapping_for_product_and_category() -> None:
    result = performance_for("SKU,Dept,Qty,Price\nX,Food,2,3.00\n", product="SKU", category="Dept", quantity="Qty", unit_price="Price")

    assert result.columns_used == {
        "product": "SKU",
        "category": "Dept",
        "order_id": None,
        "quantity": "Qty",
        "unit_price": "Price",
        "revenue": None,
    }
    assert group(result.products, "X").revenue == 6.0
    assert group(result.products, "X").categories == ["Food"]
    assert result.products.columns_used == ["SKU"]


def test_similar_column_names_are_not_guessed() -> None:
    result = performance_for("Product,Category,revenue\nTea,Drinks,1\n")

    assert result.columns_used["product"] is None
    assert result.columns_used["category"] is None
    assert result.products.status == "unavailable"


def test_mapping_to_a_missing_column_is_an_error() -> None:
    with pytest.raises(ColumnMappingError, match="product_column is 'SKU'"):
        resolve_performance_columns(["product", "revenue"], {"product": "SKU"})


def test_one_column_cannot_be_both_product_and_category() -> None:
    with pytest.raises(ColumnMappingError, match="more than one role"):
        resolve_performance_columns(["product", "revenue"], {"category": "product"})


# ---------- Safety ----------


def test_revenue_too_large_to_total_is_unavailable_and_ranking_falls_back() -> None:
    big = "9" * 30
    products = performance_for(f"product,quantity,revenue\nA,1,{big}\nA,2,{big}\nB,5,1\n").products

    assert products.revenue.status == "unavailable"
    assert "too large" in products.revenue.notes[0]
    assert products.ranked_by == "quantity"
    assert labels(products) == ["B", "A"]


def test_hostile_column_names_and_labels_are_handled_safely() -> None:
    hostile = 'p"); DROP TABLE uploaded_rows; --'
    csv_text = f'"{hostile.replace(chr(34), chr(34) * 2)}",revenue\n"\'; DELETE FROM x; --",3\n'

    products = performance_for(csv_text, product=hostile).products

    assert labels(products) == ["'; DELETE FROM x; --"]
    assert products.groups[0].revenue == 3.0


def test_calculating_never_modifies_the_parsed_data() -> None:
    parsed = parse_csv(CATALOG.encode("utf-8"))
    before = copy.deepcopy(parsed)

    calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, {}))

    assert parsed == before
