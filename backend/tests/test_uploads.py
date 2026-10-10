"""API tests for POST /api/uploads/csv: status codes and JSON responses."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app

UPLOAD_URL = "/api/uploads/csv"
SAMPLE_CSV = Path(__file__).parent / "fixtures" / "sample_sales.csv"


def make_client(settings: Settings | None = None) -> TestClient:
    app = create_app()
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def upload(client: TestClient, filename: str, content: bytes, content_type: str = "text/csv"):
    return client.post(UPLOAD_URL, files={"file": (filename, content, content_type)})


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
