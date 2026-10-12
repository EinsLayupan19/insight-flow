"""HTTP tests for the narrator status and narrations of saved insights analyses."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.narration import get_narrator_dependency
from app.config import Settings, get_settings
from app.main import create_app
from app.narration.providers import NarratorStatus

DATASETS_URL = "/api/datasets"


def month_rows(month: str, values: list[float], last_day: int | None = None) -> list[str]:
    rows = []
    for i, value in enumerate(values):
        day = last_day if last_day is not None and i == len(values) - 1 else 1 + i
        rows.append(f"{month}-{i},{month}-{day:02d},A,General,{value}")
    return rows


THREE_MONTHS = (
    "order_id,order_date,product,category,revenue\n"
    + "\n".join(month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6, last_day=31))
    + "\n"
).encode("utf-8")


class FakeNarrator:
    provider = "fake"
    model = "fake-model"

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def status(self) -> NarratorStatus:
        return NarratorStatus(enabled=True, provider="fake", model="fake-model", available=True, reason=None)

    def write(self, system: str, prompt: str) -> str:
        return self.reply


def client_with(data_dir: Path, narrator: FakeNarrator | None) -> TestClient:
    settings = Settings(data_dir=data_dir, _env_file=None)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_narrator_dependency] = lambda: narrator
    return TestClient(app)


@pytest.fixture
def saved(library_client: TestClient) -> tuple[int, int, int]:
    dataset_id = library_client.post(DATASETS_URL, files={"file": ("sales.csv", THREE_MONTHS, "text/csv")}).json()["dataset"]["id"]
    insights_id = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "insights"}).json()["id"]
    metrics_id = library_client.post(f"{DATASETS_URL}/{dataset_id}/analyses", json={"kind": "metrics"}).json()["id"]
    return dataset_id, insights_id, metrics_id


def narrations_url(dataset_id: int, analysis_id: int) -> str:
    return f"{DATASETS_URL}/{dataset_id}/analyses/{analysis_id}/narrations"


def test_the_narrator_is_off_by_default_and_says_how_to_turn_it_on(library_client: TestClient) -> None:
    response = library_client.get("/api/insights/narrator")

    assert response.status_code == 200
    body = response.json()
    assert (body["enabled"], body["available"], body["provider"], body["model"]) == (False, False, None, None)
    assert "INSIGHTS_NARRATOR=ollama" in body["reason"]
    assert set(body) == {"enabled", "provider", "model", "available", "reason"}  # no URLs or keys


def test_narrating_without_a_narrator_returns_409(library_client: TestClient, saved) -> None:
    dataset_id, insights_id, _ = saved

    response = library_client.post(narrations_url(dataset_id, insights_id))

    assert response.status_code == 409
    assert "No narrator is configured" in response.json()["detail"]
    assert library_client.get(narrations_url(dataset_id, insights_id)).json() == {"narrations": []}


def test_a_narration_is_recorded_and_listed(data_dir: Path, saved) -> None:
    dataset_id, insights_id, _ = saved
    client = client_with(data_dir, FakeNarrator("Revenue was 120.00 in March 2026, down 30.00 from 150.00 in February 2026."))

    created = client.post(narrations_url(dataset_id, insights_id))

    assert created.status_code == 201
    record = created.json()
    assert (record["status"], record["source"], record["provider"], record["model"], record["prompt_version"]) == (
        "accepted", "ai", "fake", "fake-model", "narration-v1",
    )
    assert client.get(narrations_url(dataset_id, insights_id)).json() == {"narrations": [record]}
    assert client.get("/api/insights/narrator").json()["available"] is True


def test_a_rejected_narration_shows_the_template_and_never_the_rejected_text(data_dir: Path, saved) -> None:
    dataset_id, insights_id, _ = saved
    client = client_with(data_dir, FakeNarrator("Sales fell 99% because <script>alert(1)</script> customers left."))

    record = client.post(narrations_url(dataset_id, insights_id)).json()

    assert (record["status"], record["source"]) == ("rejected", "template")
    assert record["text"].startswith("Key findings by month:")
    assert "script" not in record["text"] and "customers left" not in str(record)


def test_only_insights_analyses_can_be_narrated(data_dir: Path, saved) -> None:
    dataset_id, _, metrics_id = saved
    client = client_with(data_dir, FakeNarrator("x"))

    response = client.post(narrations_url(dataset_id, metrics_id))

    assert response.status_code == 422
    assert "Only key findings" in response.json()["detail"]


def test_unknown_datasets_and_analyses_return_404(data_dir: Path, saved) -> None:
    dataset_id, _, _ = saved
    client = client_with(data_dir, FakeNarrator("x"))

    assert client.post(narrations_url(999, 1)).status_code == 404
    assert client.post(narrations_url(dataset_id, 999)).status_code == 404
    assert client.get(narrations_url(dataset_id, 999)).status_code == 404
