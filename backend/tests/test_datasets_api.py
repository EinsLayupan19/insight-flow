"""HTTP tests for /api/datasets: status codes, response shapes, and error messages."""

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
DATASETS_URL = "/api/datasets"
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()
SAMPLE = (FIXTURES / "sample_sales.csv").read_bytes()


def save(client: TestClient, filename: str, content: bytes, content_type: str = "text/csv"):
    return client.post(DATASETS_URL, files={"file": (filename, content, content_type)})


def saved_id(client: TestClient, content: bytes = MESSY) -> int:
    return save(client, "messy_sales.csv", content).json()["dataset"]["id"]


# ---------- Saving ----------


def test_saving_a_new_file_returns_201_and_the_dataset(library_client: TestClient) -> None:
    response = save(library_client, "messy_sales.csv", MESSY)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["dataset"]["filename"] == "messy_sales.csv"
    assert body["dataset"]["row_count"] == 6
    assert body["dataset"]["file_stored"] is True
    assert body["dataset"]["analysis_count"] == 0


def test_saving_the_same_content_again_returns_200_and_the_existing_dataset(library_client: TestClient) -> None:
    first = save(library_client, "messy_sales.csv", MESSY).json()["dataset"]

    response = save(library_client, "another name.csv", MESSY)

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["dataset"]["id"] == first["id"]


def test_saving_uses_the_same_request_checks_as_the_upload_endpoints(library_client: TestClient) -> None:
    assert library_client.post(DATASETS_URL).status_code == 400
    assert save(library_client, "sales.xlsx", b"PK\x03\x04").status_code == 415

    response = save(library_client, "empty.csv", b"store,revenue\n")
    assert response.status_code == 422
    assert response.json()["detail"] == "The file has column headers but no data rows."
    assert library_client.get(DATASETS_URL).json() == {"datasets": []}


def test_saving_respects_the_upload_size_limit(data_dir: Path) -> None:
    app = create_app()
    settings = Settings(data_dir=data_dir, max_upload_mb=1, _env_file=None)
    app.dependency_overrides[get_settings] = lambda: settings
    too_big = b"a,b\n" + b"1,2\n" * 300_000

    response = save(TestClient(app), "big.csv", too_big)

    assert response.status_code == 413


# ---------- Listing and details ----------


def test_empty_library_lists_no_datasets(library_client: TestClient) -> None:
    response = library_client.get(DATASETS_URL)

    assert response.status_code == 200
    assert response.json() == {"datasets": []}


def test_list_is_newest_first(library_client: TestClient) -> None:
    older = saved_id(library_client, MESSY)
    newer = saved_id(library_client, SAMPLE)

    datasets = library_client.get(DATASETS_URL).json()["datasets"]

    assert [dataset["id"] for dataset in datasets] == [newer, older]


def test_dataset_details_include_columns(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)

    response = library_client.get(f"{DATASETS_URL}/{dataset_id}")

    assert response.status_code == 200
    assert response.json()["columns"] == ["order_id", "order_date", "store", "product", "quantity", "unit_price", "discount_code"]


def test_unknown_dataset_returns_404_with_a_clear_message(library_client: TestClient) -> None:
    response = library_client.get(f"{DATASETS_URL}/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Dataset 999 was not found. It may have been deleted."


# ---------- Analyses and history ----------


def test_running_a_profile_records_it_in_the_history(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)

    response = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "profile"})

    assert response.status_code == 201
    record = response.json()
    assert record["kind"] == "profile"
    assert record["app_version"] == __version__
    assert record["result"]["duplicate_row_count"] == 1
    history = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").json()["analyses"]
    assert [entry["id"] for entry in history] == [record["id"]]
    assert history[0]["highlights"] == {"duplicate_row_count": 1, "missing_value_count": 5, "type_mismatch_count": 3}


def test_metrics_with_a_column_mapping(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client, b"OrderNo,Qty,Price\nX1,2,3.00\nX2,1,4.00\n")

    response = library_client.post(
        f"{DATASETS_URL}/{dataset_id}/analyses",
        json={"kind": "metrics", "column_mapping": {"order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price"}},
    )

    assert response.status_code == 201
    record = response.json()
    assert record["result"]["average_order_value"]["value"] == 5.0
    assert record["column_mapping"] == {"order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price"}


def test_a_stored_analysis_can_be_read_back_exactly(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)
    created = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "metrics"}).json()

    response = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_invalid_analysis_requests_are_rejected(library_client: TestClient) -> None:
    url = f"{DATASETS_URL}/{saved_id(library_client)}/analyses"

    assert library_client.post(url, json={"kind": "profit"}).status_code == 422
    assert library_client.post(url, json={"kind": "profile", "column_mapping": {"quantity": "x"}}).status_code == 422
    assert library_client.post(url, json={"kind": "metrics", "column_mapping": {"discount": "x"}}).status_code == 422

    unknown_column = library_client.post(url, json={"kind": "metrics", "column_mapping": {"quantity": "Qty"}})
    assert unknown_column.status_code == 422
    assert "quantity_column is 'Qty'" in unknown_column.json()["detail"]
    assert library_client.get(url).json() == {"analyses": []}


def test_analysis_ids_are_scoped_to_their_dataset(library_client: TestClient) -> None:
    first = saved_id(library_client, MESSY)
    second = saved_id(library_client, SAMPLE)
    record = library_client.post(f"{DATASETS_URL}/{first}/analyses", json={"kind": "profile"}).json()

    response = library_client.get(f"{DATASETS_URL}/{second}/analyses/{record['id']}")

    assert response.status_code == 404
    assert library_client.post(f"{DATASETS_URL}/999/analyses", json={"kind": "profile"}).status_code == 404


def test_missing_stored_file_returns_409_with_advice(library_client: TestClient, data_dir: Path) -> None:
    dataset = save(library_client, "messy_sales.csv", MESSY).json()["dataset"]
    (data_dir / "uploads" / f"{dataset['sha256']}.csv").unlink()

    response = library_client.post(f"{DATASETS_URL}/{dataset['id']}/analyses", json={"kind": "profile"})

    assert response.status_code == 409
    assert "Delete the dataset and save the file again" in response.json()["detail"]
    assert library_client.get(f"{DATASETS_URL}/{dataset['id']}").json()["file_stored"] is False


# ---------- Deleting ----------


def test_deleting_returns_204_and_removes_everything(library_client: TestClient, data_dir: Path) -> None:
    dataset_id = saved_id(library_client)
    library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "profile"})

    response = library_client.delete(f"{DATASETS_URL}/{dataset_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert library_client.get(f"{DATASETS_URL}/{dataset_id}").status_code == 404
    assert library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").status_code == 404
    assert list((data_dir / "uploads").iterdir()) == []
    assert library_client.delete(f"{DATASETS_URL}/{dataset_id}").status_code == 404


# ---------- In-memory endpoints stay in memory ----------


def test_in_memory_endpoints_never_save_anything(library_client: TestClient, data_dir: Path) -> None:
    files = {"file": ("messy_sales.csv", MESSY, "text/csv")}
    for url in ("/api/uploads/csv", "/api/uploads/csv/profile", "/api/uploads/csv/metrics"):
        assert library_client.post(url, files=files).status_code == 200

    assert not data_dir.exists()
