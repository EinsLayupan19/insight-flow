"""Data-quality profile of a parsed CSV: missing values, duplicate rows, and types.

This module only *reports*. It never changes, trims, converts, or removes
uploaded values. Every metric is defined in METRIC_DEFINITIONS, which is
returned with the report so readers know exactly what each number means.
"""

import re
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.ingestion.csv_parser import CsvRow, ParsedCsv

ValueType = Literal["boolean", "integer", "decimal", "date", "datetime", "text"]
InferredType = Literal["boolean", "integer", "decimal", "date", "datetime", "text", "empty"]
TYPE_ORDER: list[ValueType] = ["boolean", "integer", "decimal", "date", "datetime", "text"]

MAX_MISMATCH_EXAMPLES = 3
MAX_DUPLICATE_EXAMPLES = 5

METRIC_DEFINITIONS: dict[str, str] = {
    "line": "Line number in the file where a row starts. The header is usually line 1.",
    "row_count": "Number of data rows. The header row and completely blank lines are not counted.",
    "column_count": "Number of columns in the header row.",
    "duplicate_row_count": (
        "Rows that exactly match an earlier row in every column. Matching is exact text: "
        "'North' and 'north ' are different. The first copy is not counted, so 3 identical rows count as 2."
    ),
    "duplicate_row_percent": "duplicate_row_count / row_count x 100, rounded to 2 decimals. 0 when there are no rows.",
    "missing_count": (
        "Cells that are empty or contain only spaces. Placeholder text such as 'N/A' or 'null' "
        "is NOT counted as missing; it is a value and may appear as a type mismatch instead."
    ),
    "missing_percent": "missing_count / row_count x 100, rounded to 2 decimals. 0 when there are no rows.",
    "type_counts": (
        "How many non-missing values look like each type, checked after ignoring surrounding spaces. "
        "boolean: true/false/yes/no (any case). integer: whole numbers such as 42 or -7. "
        "decimal: numbers with a decimal point such as 3.14 (no currency symbols or thousands separators). "
        "date: a real calendar date written YYYY-MM-DD. "
        "datetime: YYYY-MM-DD followed by a time (HH:MM or HH:MM:SS). text: anything else."
    ),
    "inferred_type": (
        "The most specific type matched by more than half of the non-missing values. "
        "Integers also count as decimals. 'text' if no type reaches a majority; "
        "'empty' if every value is missing."
    ),
    "mismatch_count": (
        "Non-missing values that do not match the inferred type. Always 0 for 'text' and 'empty' columns."
    ),
    "mismatch_examples": f"Up to {MAX_MISMATCH_EXAMPLES} mismatching values, with the line where each appears.",
    "duplicate_examples": f"Up to {MAX_DUPLICATE_EXAMPLES} duplicate rows, with the line of the earlier copy.",
}


class ValueExample(BaseModel):
    line: int
    value: str


class DuplicateExample(BaseModel):
    line: int
    duplicate_of_line: int


class ColumnProfile(BaseModel):
    name: str
    missing_count: int
    missing_percent: float
    inferred_type: InferredType
    type_counts: dict[ValueType, int]
    mismatch_count: int
    mismatch_examples: list[ValueExample]


class QualityReport(BaseModel):
    row_count: int
    column_count: int
    duplicate_row_count: int
    duplicate_row_percent: float
    duplicate_examples: list[DuplicateExample]
    columns: list[ColumnProfile]
    definitions: dict[str, str]


def profile_csv(parsed: ParsedCsv) -> QualityReport:
    """Build a data-quality report. Reads `parsed` only; nothing is modified."""
    row_count = len(parsed.rows)
    duplicate_count, duplicate_examples = _find_duplicate_rows(parsed.rows)
    columns = [
        _profile_column(name, index, parsed.rows) for index, name in enumerate(parsed.columns)
    ]
    return QualityReport(
        row_count=row_count,
        column_count=len(parsed.columns),
        duplicate_row_count=duplicate_count,
        duplicate_row_percent=_percent(duplicate_count, row_count),
        duplicate_examples=duplicate_examples,
        columns=columns,
        definitions=METRIC_DEFINITIONS,
    )


# ---------- Duplicate rows ----------


def _find_duplicate_rows(rows: list[CsvRow]) -> tuple[int, list[DuplicateExample]]:
    first_seen: dict[tuple[str, ...], int] = {}  # row values -> line of first copy
    count = 0
    examples: list[DuplicateExample] = []
    for row in rows:
        key = tuple(row.values)
        if key not in first_seen:
            first_seen[key] = row.line
            continue
        count += 1
        if len(examples) < MAX_DUPLICATE_EXAMPLES:
            examples.append(DuplicateExample(line=row.line, duplicate_of_line=first_seen[key]))
    return count, examples


# ---------- Columns ----------


def _profile_column(name: str, index: int, rows: list[CsvRow]) -> ColumnProfile:
    present: list[tuple[CsvRow, ValueType]] = []  # non-missing values and their detected type
    missing = 0
    for row in rows:
        value = row.values[index]
        if value.strip() == "":
            missing += 1
        else:
            present.append((row, detect_type(value)))

    type_counts = Counter(value_type for _, value_type in present)
    inferred = _infer_type(type_counts, len(present))
    mismatches = [
        ValueExample(line=row.line, value=row.values[index])
        for row, value_type in present
        if not _is_compatible(value_type, inferred)
    ]
    return ColumnProfile(
        name=name,
        missing_count=missing,
        missing_percent=_percent(missing, len(rows)),
        inferred_type=inferred,
        type_counts={t: type_counts[t] for t in TYPE_ORDER if type_counts[t]},
        mismatch_count=len(mismatches),
        mismatch_examples=mismatches[:MAX_MISMATCH_EXAMPLES],
    )


# ---------- Type detection and inference ----------

# Which detected value types are acceptable for each inferred column type.
COMPATIBLE: dict[ValueType, set[ValueType]] = {
    "boolean": {"boolean"},
    "integer": {"integer"},
    "decimal": {"integer", "decimal"},
    "date": {"date"},
    "datetime": {"datetime"},
}

BOOLEAN_WORDS = {"true", "false", "yes", "no"}
INTEGER_PATTERN = re.compile(r"[+-]?[0-9]+")
DECIMAL_PATTERN = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)")
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
DATETIME_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?")


def detect_type(value: str) -> ValueType:
    """Classify one non-missing cell by what its text looks like."""
    text = value.strip()
    if text.lower() in BOOLEAN_WORDS:
        return "boolean"
    if INTEGER_PATTERN.fullmatch(text):
        return "integer"
    if DECIMAL_PATTERN.fullmatch(text):
        return "decimal"
    if DATE_PATTERN.fullmatch(text) and _is_real(date.fromisoformat, text):
        return "date"
    if DATETIME_PATTERN.fullmatch(text) and _is_real(datetime.fromisoformat, text):
        return "datetime"
    return "text"


def _is_real(parse: Callable[[str], object], text: str) -> bool:
    # The pattern checks the shape; parsing rejects impossible values like 2026-02-30.
    try:
        parse(text)
    except ValueError:
        return False
    return True


def _infer_type(type_counts: Counter[ValueType], present_count: int) -> InferredType:
    if present_count == 0:
        return "empty"
    best: InferredType = "text"
    best_count = 0
    for candidate, accepted in COMPATIBLE.items():  # most specific first, so ties keep the earlier type
        count = sum(type_counts[t] for t in accepted)
        if count > best_count:
            best, best_count = candidate, count
    return best if best_count * 2 > present_count else "text"


def _is_compatible(value_type: ValueType, inferred: InferredType) -> bool:
    if inferred in ("text", "empty"):
        return True
    return value_type in COMPATIBLE[inferred]


def _percent(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0
