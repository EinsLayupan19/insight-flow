"""HTTP tests for insights: the in-memory endpoint and insights analyses on saved datasets."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
INSIGHTS_URL = "/api/uploads/csv/insights"
DATASETS_URL = "/api/datasets"


def month_rows(month: str, values: list[float], last_day: int | None = None, product: str = "A") -> list[str]:
    rows = []
    for i, value in enumerate(values):
        day = last_day if last_day is not None and i == len(values) - 1 else 1 + i
        rows.append(f"{month}-{product}-{i},{month}-{day:02d},{product},General,{value}")
    return rows


# Jan 100, Feb 150, Mar 120; the dates cover all three months completely.
THREE_MONTHS = (
    "order_id,order_date,product,category,revenue\n"
    + "\n".join(month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6, last_day=31))
    + "\n"
).encode("utf-8")
RENAMED = THREE_MONTHS.replace(b"order_id,order_date,product,category,revenue", b"OrderNo,Day,SKU,Dept,Amount")


def post_insights(client: TestClient, content: bytes, **form: str):
    return client.post(INSIGHTS_URL, files={"file": ("sales.csv", content, "text/csv")}, data=form)


# ---------- POST /api/uploads/csv/insights ----------


def test_insights_for_three_complete_months() -> None:
    response = post_insights(TestClient(create_app()), THREE_MONTHS)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "sales.csv"
    insights = body["insights"]
    assert insights["grain"] == "month"
    revenue = next(item for item in insights["insights"] if item["id"] == "period_change.revenue")
    assert revenue["statement"] == "Revenue was 120.00 in March 2026, down 30.00 (20.0%) from 150.00 in February 2026."
    assert revenue["evidence"][0]["period"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert insights["thresholds"]["min_rows_per_period"] == 5
    assert insights["coverage"]["complete_periods"] == 3


def test_insights_accept_a_grain_and_column_mapping() -> None:
    response = post_insights(
        TestClient(create_app()),
        RENAMED,
        grain="week",
        order_id_column="OrderNo",
        order_date_column="Day",
        product_column="SKU",
        category_column="Dept",
        revenue_column="Amount",
    )

    assert response.status_code == 200
    insights = response.json()["insights"]
    assert insights["grain"] == "week"
    assert insights["columns_used"]["order_date"] == "Day"


def test_insights_report_what_could_not_be_assessed() -> None:
    response = post_insights(TestClient(create_app()), (FIXTURES / "order_lines.csv").read_bytes())

    assert response.status_code == 200
    reasons = {check["kind"]: check["reason"] for check in response.json()["insights"]["not_assessed"]}
    assert "No column named 'order_date'" in reasons["period_change"]


def test_insights_with_an_unknown_mapped_column_return_422() -> None:
    response = post_insights(TestClient(create_app()), THREE_MONTHS, order_date_column="Date")

    assert response.status_code == 422
    assert "order_date_column is 'Date'" in response.json()["detail"]


def test_insights_reject_an_unknown_grain_and_bad_requests() -> None:
    client = TestClient(create_app())

    assert post_insights(client, THREE_MONTHS, grain="year").status_code == 422
    assert client.post(INSIGHTS_URL).status_code == 400
    assert client.post(INSIGHTS_URL, files={"file": ("sales.xlsx", b"PK", "text/csv")}).status_code == 415
    assert post_insights(client, b"order_date,revenue\n").status_code == 422


def test_the_insights_endpoint_never_saves_anything(library_client: TestClient, data_dir: Path) -> None:
    assert post_insights(library_client, THREE_MONTHS).status_code == 200

    assert not data_dir.exists()


# ---------- Insights analyses on saved datasets ----------


def saved_id(client: TestClient, content: bytes = THREE_MONTHS) -> int:
    return client.post(DATASETS_URL, files={"file": ("sales.csv", content, "text/csv")}).json()["dataset"]["id"]


def test_running_insights_records_them_in_the_history(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client)

    response = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "insights"})

    assert response.status_code == 201
    record = response.json()
    assert record["kind"] == "insights"
    assert record["grain"] == "month"
    assert record["result"]["insights"][0]["importance"] == "high"
    history = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses").json()["analyses"]
    highlights = history[0]["highlights"]
    assert highlights["grain"] == "month"
    assert highlights["finding_count"] == len(record["result"]["insights"])
    assert highlights["high_count"] == sum(item["importance"] == "high" for item in record["result"]["insights"])
    assert highlights["not_assessed_count"] == len(record["result"]["not_assessed"])


def test_insights_with_a_mapping_read_back_exactly(library_client: TestClient) -> None:
    dataset_id = saved_id(library_client, RENAMED)
    mapping = {"order_id": "OrderNo", "order_date": "Day", "product": "SKU", "category": "Dept", "revenue": "Amount"}

    created = library_client.post(
        f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "insights", "grain": "week", "column_mapping": mapping}
    ).json()
    response = library_client.get(f"{DATASETS_URL}/{dataset_id}/analyses/{created['id']}")

    assert created["column_mapping"] == mapping
    assert created["grain"] == "week"
    assert response.json() == created


def test_invalid_insights_requests_are_rejected_and_record_nothing(library_client: TestClient) -> None:
    url = f"{DATASETS_URL}/{saved_id(library_client)}/analyses"

    assert library_client.post(url, json={"kind": "insights", "grain": "year"}).status_code == 422
    unknown = library_client.post(url, json={"kind": "insights", "column_mapping": {"product": "SKU"}})
    assert unknown.status_code == 422
    assert "product_column is 'SKU'" in unknown.json()["detail"]
    assert library_client.get(url).json() == {"analyses": []}


def test_insights_need_the_stored_file(library_client: TestClient, data_dir: Path) -> None:
    dataset = library_client.post(DATASETS_URL, files={"file": ("sales.csv", THREE_MONTHS, "text/csv")}).json()["dataset"]
    (data_dir / "uploads" / f"{dataset['sha256']}.csv").unlink()

    response = library_client.post(f"{DATASETS_URL}/{dataset['id']}/analyses", json={"kind": "insights"})

    assert response.status_code == 409
