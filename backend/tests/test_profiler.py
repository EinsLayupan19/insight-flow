"""Unit tests for the data-quality profiler: CSV text in, quality report out."""

import copy

import pytest

from app.ingestion.csv_parser import ParsedCsv, parse_csv
from app.ingestion.profiler import (
    METRIC_DEFINITIONS,
    ColumnProfile,
    QualityReport,
    detect_type,
    profile_csv,
)


def profile(text: str) -> QualityReport:
    return profile_csv(parse_csv(text.encode("utf-8")))


def column(report: QualityReport, name: str) -> ColumnProfile:
    return next(c for c in report.columns if c.name == name)


# ---------- Clean data ----------


def test_clean_data_has_no_issues_and_correct_types() -> None:
    report = profile(
        "id,active,price,order_date,created_at,store\n"
        "1,true,18.50,2026-01-05,2026-01-05 09:30,North\n"
        "2,false,4.25,2026-01-06,2026-01-06T14:05:00,South\n"
    )

    assert report.row_count == 2
    assert report.column_count == 6
    assert report.duplicate_row_count == 0
    assert {c.name: c.inferred_type for c in report.columns} == {
        "id": "integer",
        "active": "boolean",
        "price": "decimal",
        "order_date": "date",
        "created_at": "datetime",
        "store": "text",
    }
    for c in report.columns:
        assert c.missing_count == 0
        assert c.mismatch_count == 0


# ---------- Missing values ----------


def test_empty_and_space_only_cells_count_as_missing() -> None:
    report = profile("store,revenue\nNorth,100\n,200\n   ,300\nSouth,\n")

    store = column(report, "store")
    assert store.missing_count == 2
    assert store.missing_percent == 50.0
    assert column(report, "revenue").missing_count == 1


def test_placeholder_text_is_a_value_not_missing() -> None:
    report = profile("quantity\n5\nN/A\nnull\n7\n9\n")

    quantity = column(report, "quantity")
    assert quantity.missing_count == 0
    assert quantity.inferred_type == "integer"
    assert quantity.mismatch_count == 2  # "N/A" and "null" are reported as mismatches instead


def test_column_with_every_value_missing_is_empty() -> None:
    report = profile("store,notes\nNorth,\nSouth,  \n")

    notes = column(report, "notes")
    assert notes.inferred_type == "empty"
    assert notes.missing_percent == 100.0
    assert notes.type_counts == {}
    assert notes.mismatch_count == 0


# ---------- Duplicate rows ----------


def test_exact_duplicate_rows_are_counted_after_the_first_copy() -> None:
    report = profile("store,revenue\nNorth,100\nSouth,200\nNorth,100\nNorth,100\n")

    assert report.duplicate_row_count == 2
    assert report.duplicate_row_percent == 50.0
    assert [(d.line, d.duplicate_of_line) for d in report.duplicate_examples] == [(4, 2), (5, 2)]


def test_rows_differing_only_by_case_or_spaces_are_not_duplicates() -> None:
    report = profile("store,revenue\nNorth,100\nnorth,100\nNorth ,100\n")

    assert report.duplicate_row_count == 0


# ---------- Mixed data types ----------


def test_mismatches_are_counted_with_line_numbers() -> None:
    report = profile("quantity\n2\n5\nN/A\n4\ntwo\n")

    quantity = column(report, "quantity")
    assert quantity.inferred_type == "integer"
    assert quantity.type_counts == {"integer": 3, "text": 2}
    assert quantity.mismatch_count == 2
    assert [(e.line, e.value) for e in quantity.mismatch_examples] == [(4, "N/A"), (6, "two")]


def test_integers_and_decimals_together_are_decimal_without_mismatches() -> None:
    price = column(profile("price\n3\n4.50\n5\n"), "price")

    assert price.inferred_type == "decimal"
    assert price.mismatch_count == 0


def test_no_majority_type_means_text() -> None:
    mixed = column(profile("code\n1\n2\nA\nB\ntrue\n"), "code")

    assert mixed.inferred_type == "text"
    assert mixed.mismatch_count == 0


def test_impossible_date_is_a_mismatch() -> None:
    order_date = column(profile("order_date\n2026-01-05\n2026-02-30\n2026-01-07\n"), "order_date")

    assert order_date.inferred_type == "date"
    assert order_date.mismatch_count == 1
    assert order_date.mismatch_examples[0].value == "2026-02-30"


def test_mismatch_examples_are_capped_but_count_is_complete() -> None:
    rows = "\n".join(["1"] * 10 + ["bad"] * 5)
    quantity = column(profile(f"quantity\n{rows}\n"), "quantity")

    assert quantity.mismatch_count == 5
    assert len(quantity.mismatch_examples) == 3


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42", "integer"),
        ("-7", "integer"),
        (" 12 ", "integer"),
        ("3.14", "decimal"),
        ("-.5", "decimal"),
        ("1,000", "text"),
        ("$18.50", "text"),
        ("TRUE", "boolean"),
        ("no", "boolean"),
        ("2026-01-05", "date"),
        ("2026-02-30", "text"),
        ("05/01/2026", "text"),
        ("2026-01-05 09:30", "datetime"),
        ("2026-01-05T09:30:15", "datetime"),
        ("N/A", "text"),
    ],
)
def test_detect_type(value: str, expected: str) -> None:
    assert detect_type(value) == expected


# ---------- Empty dataset and safety ----------


def test_empty_dataset_reports_zeros_instead_of_crashing() -> None:
    # The upload endpoint rejects header-only files, but the profiler itself must still be safe.
    report = profile_csv(ParsedCsv(columns=["store", "revenue"], rows=[]))

    assert report.row_count == 0
    assert report.duplicate_row_count == 0
    assert report.duplicate_row_percent == 0.0
    for c in report.columns:
        assert c.missing_percent == 0.0
        assert c.inferred_type == "empty"


def test_profiling_never_modifies_the_data() -> None:
    parsed = parse_csv(b"store,quantity\n North ,  12 \nNorth,N/A\n North ,  12 \n")
    before = copy.deepcopy(parsed)

    profile_csv(parsed)

    assert parsed == before
    assert parsed.rows[0].values == [" North ", "  12 "]


def test_every_reported_metric_has_a_definition() -> None:
    not_metrics = {"name", "columns", "definitions"}
    fields = (set(QualityReport.model_fields) | set(ColumnProfile.model_fields)) - not_metrics

    assert fields <= set(METRIC_DEFINITIONS)
