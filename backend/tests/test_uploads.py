"""API tests for POST /api/uploads/csv: status codes and JSON responses."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app

UPLOAD_URL = "/api/uploads/csv"
PROFILE_URL = "/api/uploads/csv/profile"
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_sales.csv"
MESSY_CSV = FIXTURES / "messy_sales.csv"


def make_client(settings: Settings | None = None) -> TestClient:
    app = create_app()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def upload(client: TestClient, filename: str, content: bytes, content_type: str = "text/csv", url: str = UPLOAD_URL):
    return client.post(url, files={"file": (filename, content, content_type)})


def test_valid_csv_returns_metadata() -> None:
    content = SAMPLE_CSV.read_bytes()

    response = upload(make_client(), "sample_sales.csv", content)

    assert response.status_code == 200
    assert response.json() == {
        "filename": "sample_sales.csv",
        "size_bytes": len(content),
        "row_count": 5,
        "column_count": 7,
        "columns": ["order_id", "order_date", "store", "product", "quantity", "unit_price", "unit_cost"],
    }


def test_csv_extension_check_ignores_case_and_content_type() -> None:
    # Windows browsers often label .csv files as Excel files.
    response = upload(make_client(), "SALES.CSV", b"a,b\n1,2\n", "application/vnd.ms-excel")

    assert response.status_code == 200


def test_missing_file_returns_400() -> None:
    response = make_client().post(UPLOAD_URL)

    assert response.status_code == 400
    assert "No file was uploaded" in response.json()["detail"]


def test_file_in_wrong_form_field_returns_400() -> None:
    response = make_client().post(UPLOAD_URL, files={"upload": ("sales.csv", b"a,b\n1,2\n", "text/csv")})

    assert response.status_code == 400


def test_non_csv_extension_returns_415() -> None:
    response = upload(make_client(), "sales.xlsx", b"PK\x03\x04 binary excel data")

    assert response.status_code == 415
    assert "not a CSV file" in response.json()["detail"]


def test_file_over_size_limit_returns_413() -> None:
    settings = Settings(max_upload_mb=1, _env_file=None)
    too_big = b"a,b\n" + b"1,2\n" * 300_000  # about 1.2 MB

    response = upload(make_client(settings), "big.csv", too_big)

    assert response.status_code == 413
    assert "1 MB limit" in response.json()["detail"]


def test_unparseable_csv_returns_422_with_reason() -> None:
    response = upload(make_client(), "broken.csv", b"store,revenue\nNorth,100,extra\n")

    assert response.status_code == 422
    assert response.json()["detail"] == "Line 2 has 3 values, but the header has 2 columns."


def test_empty_csv_returns_422() -> None:
    response = upload(make_client(), "empty.csv", b"")

    assert response.status_code == 422
    assert response.json()["detail"] == "The file is empty."


# ---------- POST /api/uploads/csv/profile ----------


def test_profile_reports_known_issues_in_messy_file() -> None:
    response = upload(make_client(), "messy_sales.csv", MESSY_CSV.read_bytes(), url=PROFILE_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "messy_sales.csv"
    report = body["profile"]
    assert report["row_count"] == 6
    assert report["column_count"] == 7
    assert report["duplicate_row_count"] == 1
    assert report["duplicate_row_percent"] == 16.67
    assert report["duplicate_examples"] == [{"line": 5, "duplicate_of_line": 3}]

    columns = {c["name"]: c for c in report["columns"]}
    assert columns["order_id"]["inferred_type"] == "integer"
    assert columns["unit_price"]["inferred_type"] == "decimal"
    assert columns["store"]["missing_count"] == 1
    assert columns["discount_code"]["missing_count"] == 4
    assert columns["discount_code"]["missing_percent"] == 66.67
    assert columns["order_date"]["inferred_type"] == "date"
    assert columns["order_date"]["mismatch_examples"] == [{"line": 6, "value": "2026-02-30"}]
    assert columns["quantity"]["inferred_type"] == "integer"
    assert columns["quantity"]["mismatch_examples"] == [{"line": 4, "value": "N/A"}, {"line": 7, "value": "two"}]
    assert "missing_count" in report["definitions"]


def test_profile_of_clean_file_has_no_issues() -> None:
    response = upload(make_client(), "sample_sales.csv", SAMPLE_CSV.read_bytes(), url=PROFILE_URL)

    report = response.json()["profile"]
    assert report["duplicate_row_count"] == 0
    assert all(c["missing_count"] == 0 and c["mismatch_count"] == 0 for c in report["columns"])


def test_profile_rejects_header_only_file_with_422() -> None:
    response = upload(make_client(), "empty.csv", b"store,revenue\n", url=PROFILE_URL)

    assert response.status_code == 422
    assert response.json()["detail"] == "The file has column headers but no data rows."


def test_profile_uses_same_request_checks_as_upload() -> None:
    client = make_client()

    assert client.post(PROFILE_URL).status_code == 400
    assert upload(client, "sales.xlsx", b"PK\x03\x04", url=PROFILE_URL).status_code == 415


# ---------- POST /api/uploads/csv/metrics ----------

METRICS_URL = "/api/uploads/csv/metrics"


def post_metrics(client: TestClient, filename: str, content: bytes, **form: str):
    return client.post(METRICS_URL, files={"file": (filename, content, "text/csv")}, data=form)


def test_metrics_for_sample_file() -> None:
    response = post_metrics(make_client(), "sample_sales.csv", SAMPLE_CSV.read_bytes())

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["total_revenue"]["status"] == "calculated"
    assert metrics["total_revenue"]["value"] == 140.95
    assert metrics["average_order_value"]["value"] == 28.19
    assert metrics["columns_used"]["revenue"] is None


def test_metrics_accept_column_mapping_form_fields() -> None:
    content = b"OrderNo,Qty,Price\nX1,2,3.00\nX2,1,4.00\n"

    response = post_metrics(make_client(), "renamed.csv", content, order_id_column="OrderNo", quantity_column="Qty", unit_price_column="Price")

    assert response.status_code == 200
    assert response.json()["metrics"]["average_order_value"]["value"] == 5.0


def test_metrics_report_unavailable_when_columns_are_missing() -> None:
    response = post_metrics(make_client(), "no_sales_columns.csv", (FIXTURES / "no_sales_columns.csv").read_bytes())

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["row_count"]["value"] == 2
    assert metrics["total_revenue"]["status"] == "unavailable"
    assert metrics["total_revenue"]["value"] is None


def test_metrics_with_unknown_mapped_column_returns_422() -> None:
    response = post_metrics(make_client(), "sample_sales.csv", SAMPLE_CSV.read_bytes(), quantity_column="Qty")

    assert response.status_code == 422
    assert "quantity_column is 'Qty'" in response.json()["detail"]


def test_metrics_use_same_request_and_content_checks() -> None:
    client = make_client()

    assert client.post(METRICS_URL).status_code == 400
    assert post_metrics(client, "sales.xlsx", b"PK\x03\x04").status_code == 415
    assert post_metrics(client, "empty.csv", b"store,revenue\n").status_code == 422
