"""HTTP tests for product and category performance: the in-memory endpoint and saved-dataset analyses."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = (FIXTURES / "catalog_sales.csv").read_bytes()
SAMPLE = (FIXTURES / "sample_sales.csv").read_bytes()
RENAMED = b"SKU,Dept,OrderNo,Qty,Price\nX,Food,O1,2,3.00\nY,Food,O2,1,4.00\n"
PERFORMANCE_URL = "/api/uploads/csv/performance"
DATASETS_URL = "/api/datasets"


def post_performance(client: TestClient, filename: str, content: bytes, **form: str):
    return client.post(PERFORMANCE_URL, files={"file": (filename, content, "text/csv")}, data=form)


# ---------- POST /api/uploads/csv/performance ----------


def test_performance_for_the_catalog_file() -> None:
    response = post_performance(TestClient(create_app()), "catalog_sales.csv", CATALOG)

    assert response.status_code == 200
    body = response.json()
    assert (body["filename"], body["size_bytes"]) == ("catalog_sales.csv", len(CATALOG))
    performance = body["performance"]
    assert performance["columns_used"]["product"] == "product"
    assert performance["columns_used"]["category"] == "category"
    products = performance["products"]
    assert products["ranked_by"] == "revenue"
    assert [group["label"] for group in products["groups"]] == ["Ceramic Mug", "Oat Milk", "Green Tea", "Coffee Beans", "green tea"]
    assert products["groups"][1]["categories"] == ["Beverages", "Dairy"]
    assert products["revenue"]["value"] == 102.8
    assert [group["label"] for group in performance["categories"]["groups"]] == ["Beverages", "Homeware", "Dairy"]
    assert "trimming" in performance["label_rule"]


def test_a_missing_category_column_is_reported_not_an_error() -> None:
    response = post_performance(TestClient(create_app()), "sample_sales.csv", SAMPLE)

    assert response.status_code == 200
    performance = response.json()["performance"]
    assert performance["products"]["status"] == "calculated"
    assert performance["categories"]["status"] == "unavailable"
    assert "category_column" in performance["categories"]["notes"][0]


def test_performance_accepts_column_mapping_form_fields() -> None:
    response = post_performance(
        TestClient(create_app()),
        "renamed.csv",
        RENAMED,
        product_column="SKU",
        category_column="Dept",
        order_id_column="OrderNo",
        quantity_column="Qty",
        unit_price_column="Price",
    )

    assert response.status_code == 200
    performance = response.json()["performance"]
    assert [(g["label"], g["revenue"]) for g in performance["products"]["groups"]] == [("X", 6.0), ("Y", 4.0)]
    assert performance["categories"]["groups"][0]["product_count"] == 2


def test_performance_with_an_unknown_mapped_column_returns_422() -> None:
    response = post_performance(TestClient(create_app()), "sample_sales.csv", SAMPLE, category_column="Dept")

    assert response.status_code == 422
    assert "category_column is 'Dept'" in response.json()["detail"]


def test_performance_with_one_column_for_two_roles_returns_422() -> None:
    response = post_performance(TestClient(create_app()), "catalog_sales.csv", CATALOG, category_column="product")

    assert response.status_code == 422
    assert "more than one role" in response.json()["detail"]


def test_performance_uses_the_same_request_and_content_checks() -> None:
    client = TestClient(create_app())

    assert client.post(PERFORMANCE_URL).status_code == 400
    assert post_performance(client, "sales.xlsx", b"PK\x03\x04").status_code == 415
    response = post_performance(client, "empty.csv", b"product,revenue\n")
    assert response.status_code == 422
    assert response.json()["detail"] == "The file has column headers but no data rows."


def test_the_performance_endpoint_never_saves_anything(library_client: TestClient, data_dir: Path) -> None:
    assert post_performance(library_client, "catalog_sales.csv", CATALOG).status_code == 200

    assert not data_dir.exists()


# ---------- Performance analyses on saved datasets ----------


def saved_id(client: TestClient, content: bytes = CATALOG) -> int:
    return client.post(DATASETS_URL, files={"file": ("sales.csv", content, "text/csv")}).json()["dataset"]["id"]


def test_running_performance_records_it_in_the_history(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)

    response = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "performance"})

    assert response.status_code == 201
    record = response.json()
    assert record["kind"] == "performance"
    assert record["column_mapping"] == {}
    assert record["result"]["products"]["group_count"] == 5
    history = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").json()["analyses"]
    assert history[0]["kind"] == "performance"
    assert history[0]["highlights"] == {"product_count": 5, "category_count": 3}


def test_unavailable_breakdowns_have_no_count_in_the_highlights(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client, SAMPLE)
    library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "performance"})

    history = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").json()["analyses"]

    assert history[0]["highlights"] == {"product_count": 4, "category_count": None}


def test_performance_with_a_column_mapping_reads_back_exactly(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client, RENAMED)
    mapping = {"product": "SKU", "category": "Dept", "order_id": "OrderNo", "quantity": "Qty", "unit_price": "Price"}

    created = library_client.post(
        f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "performance", "column_mapping": mapping}
    ).json()
    response = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses/{created['id']}")

    assert created["column_mapping"] == mapping
    assert response.status_code == 200
    assert response.json() == created


def test_invalid_performance_requests_are_rejected_and_record_nothing(library_client: TestClient) -> None:
    url = f"{DATASETS_URL}/{saved_id(library_client)}/analyses"

    assert library_client.post(url, json={"kind": "performance", "grain": "day"}).status_code == 422
    assert library_client.post(url, json={"kind": "metrics", "column_mapping": {"product": "product"}}).status_code == 422
    assert library_client.post(url, json={"kind": "trends", "column_mapping": {"category": "category"}}).status_code == 422
    assert library_client.post(url, json={"kind": "performance", "column_mapping": {"order_date": "order_date"}}).status_code == 422
    unknown_column = library_client.post(url, json={"kind": "performance", "column_mapping": {"product": "SKU"}})
    assert unknown_column.status_code == 422
    assert "product_column is 'SKU'" in unknown_column.json()["detail"]
    assert library_client.get(url).json() == {"analyses": []}


def test_performance_needs_the_stored_file(library_client: TestClient, data_dir: Path) -> None:
    dataset = library_client.post(DATASETS_URL, files={"file": ("sales.csv", CATALOG, "text/csv")}).json()["dataset"]
    (data_dir / "uploads" / f"{dataset['sha256']}.csv").unlink()

    response = library_client.post(f"{DATASETS_URL}/{dataset['id']}/analyses", json={"kind": "performance"})

    assert response.status_code == 409
