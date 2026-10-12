"""HTTP tests for sales trends: the in-memory endpoint and trends analyses on saved datasets."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "sample_sales.csv").read_bytes()
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()
RENAMED = b"Day,OrderNo,Qty,Price\n2026-01-05,X1,2,3.00\n2026-01-06,X2,1,4.00\n"
TRENDS_URL = "/api/uploads/csv/trends"
DATASETS_URL = "/api/datasets"


def post_trends(client: TestClient, filename: str, content: bytes, **form: str):
    return client.post(TRENDS_URL, files={"file": (filename, content, "text/csv")}, data=form)


# ---------- POST /api/uploads/csv/trends ----------


def test_trends_for_the_sample_file_default_to_months() -> None:
    response = post_trends(TestClient(create_app()), "sample_sales.csv", SAMPLE)

    assert response.status_code == 200
    body = response.json()
    assert (body["filename"], body["size_bytes"]) == ("sample_sales.csv", len(SAMPLE))
    trends = body["trends"]
    assert trends["grain"] == "month"
    assert trends["periods"] == [{"start": "2026-01-01", "end": "2026-01-31", "row_count": 5}]
    assert trends["revenue"]["points"] == [{"value": 140.95, "rows_included": 5}]
    assert trends["order_count"]["points"] == [{"value": 5, "rows_included": 5}]
    assert trends["columns_used"] == {
        "order_date": "order_date",
        "order_id": "order_id",
        "quantity": "quantity",
        "unit_price": "unit_price",
        "revenue": None,
    }
    assert "YYYY-MM-DD" in trends["date_rule"]


def test_trends_accept_a_grain_and_column_mapping_form_fields() -> None:
    response = post_trends(
        TestClient(create_app()),
        "renamed.csv",
        RENAMED,
        grain="day",
        order_date_column="Day",
        order_id_column="OrderNo",
        quantity_column="Qty",
        unit_price_column="Price",
    )

    assert response.status_code == 200
    trends = response.json()["trends"]
    assert [period["start"] for period in trends["periods"]] == ["2026-01-05", "2026-01-06"]
    assert [point["value"] for point in trends["revenue"]["points"]] == [6.0, 4.0]


def test_trends_report_excluded_dates_with_line_numbers() -> None:
    response = post_trends(TestClient(create_app()), "messy_sales.csv", MESSY, grain="week")

    assert response.status_code == 200
    dated_rows = response.json()["trends"]["dated_rows"]
    assert dated_rows["rows_excluded"] == 1
    assert "(lines 6)" in dated_rows["notes"][0]


def test_trends_without_a_date_column_are_unavailable_not_an_error() -> None:
    response = post_trends(TestClient(create_app()), "order_lines.csv", (FIXTURES / "order_lines.csv").read_bytes())

    assert response.status_code == 200
    trends = response.json()["trends"]
    assert trends["periods"] == []
    assert trends["revenue"]["status"] == "unavailable"
    assert "order_date_column" in trends["dated_rows"]["notes"][0]


def test_trends_with_an_unknown_mapped_column_return_422() -> None:
    response = post_trends(TestClient(create_app()), "sample_sales.csv", SAMPLE, order_date_column="Date")

    assert response.status_code == 422
    assert "order_date_column is 'Date'" in response.json()["detail"]


def test_trends_with_one_column_for_two_roles_return_422() -> None:
    response = post_trends(TestClient(create_app()), "sample_sales.csv", SAMPLE, order_id_column="order_date")

    assert response.status_code == 422
    assert "more than one role" in response.json()["detail"]


def test_trends_reject_an_unknown_grain() -> None:
    response = post_trends(TestClient(create_app()), "sample_sales.csv", SAMPLE, grain="year")

    assert response.status_code == 422


def test_trends_use_the_same_request_and_content_checks() -> None:
    client = TestClient(create_app())

    assert client.post(TRENDS_URL).status_code == 400
    assert post_trends(client, "sales.xlsx", b"PK\x03\x04").status_code == 415
    response = post_trends(client, "empty.csv", b"order_date,revenue\n")
    assert response.status_code == 422
    assert response.json()["detail"] == "The file has column headers but no data rows."


def test_the_trends_endpoint_never_saves_anything(library_client: TestClient, data_dir: Path) -> None:
    assert post_trends(library_client, "sample_sales.csv", SAMPLE).status_code == 200

    assert not data_dir.exists()


# ---------- Trends analyses on saved datasets ----------


def saved_id(client: TestClient, content: bytes = SAMPLE) -> int:
    return client.post(DATASETS_URL, files={"file": ("sales.csv", content, "text/csv")}).json()["dataset"]["id"]


def test_running_trends_records_them_in_the_history(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)

    response = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "trends", "grain": "day"})

    assert response.status_code == 201
    record = response.json()
    assert record["kind"] == "trends"
    assert record["grain"] == "day"
    assert record["column_mapping"] == {}
    assert [point["value"] for point in record["result"]["revenue"]["points"]] == [58.25, 12.0, 70.7]
    history = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").json()["analyses"]
    assert history[0]["kind"] == "trends"
    assert history[0]["highlights"] == {"grain": "day", "period_count": 3, "calculated_count": 3, "unavailable_count": 0}


def test_trends_default_to_months_and_read_back_exactly(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)
    created = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "trends"}).json()

    response = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses/{created['id']}")

    assert created["grain"] == "month"
    assert response.status_code == 200
    assert response.json() == created


def test_trends_with_a_column_mapping_including_the_date(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client, RENAMED)
    mapping = {"order_date": "Day", "order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price"}

    response = library_client.post(
        f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "trends", "grain": "week", "column_mapping": mapping}
    )

    assert response.status_code == 201
    record = response.json()
    assert record["column_mapping"] == mapping
    assert record["result"]["periods"] == [{"start": "2026-01-05", "end": "2026-01-11", "row_count": 2}]
    assert record["result"]["average_order_value"]["points"][0]["value"] == 5.0


def test_invalid_trends_requests_are_rejected_and_record_nothing(library_client: TestClient) -> None:
    url = f"{DATASETS_URL}/{saved_id(library_client)}/analyses"

    assert library_client.post(url, json={"kind": "trends", "grain": "year"}).status_code == 422
    assert library_client.post(url, json={"kind": "metrics", "grain": "day"}).status_code == 422
    assert library_client.post(url, json={"kind": "profile", "grain": "day"}).status_code == 422
    order_date_for_metrics = library_client.post(url, json={"kind": "metrics", "column_mapping": {"order_date": "order_date"}})
    assert order_date_for_metrics.status_code == 422
    unknown_column = library_client.post(url, json={"kind": "trends", "column_mapping": {"order_date": "Date"}})
    assert unknown_column.status_code == 422
    assert "order_date_column is 'Date'" in unknown_column.json()["detail"]
    assert library_client.get(url).json() == {"analyses": []}


def test_trends_need_the_stored_file(library_client: TestClient, data_dir: Path) -> None:
    dataset = library_client.post(DATASETS_URL, files={"file": ("sales.csv", SAMPLE, "text/csv")}).json()["dataset"]
    (data_dir / "uploads" / f"{dataset['sha256']}.csv").unlink()

    response = library_client.post(f"{DATASETS_URL}/{dataset['id']}/analyses", json={"kind": "trends"})

    assert response.status_code == 409
