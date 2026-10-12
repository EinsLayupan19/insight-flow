"""The optional narrator: what it is sent, how its output is checked, and how attempts are recorded.

A fake narrator stands in for the model. Nothing here needs Ollama or the network.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analytics.insights import calculate_insights, resolve_insight_columns
from app.config import Settings
from app.datasets.models import AnalysisRequest
from app.datasets.service import AnalysisNotFoundError, DatasetNotFoundError, DatasetService
from app.ingestion.csv_parser import parse_csv
from app.narration.facts import build_facts, template_summary
from app.narration.prompt import PROMPT_VERSION, build_prompt
from app.narration.providers import NarratorError, NarratorStatus, get_narrator
from app.narration.service import (
    NarrationBusyError,
    NarrationService,
    NarratorUnavailableError,
    NotNarratableError,
)
from app.narration.validation import check_narration
from app.storage.database import database_path


def month_rows(month: str, values: list[float], last_day: int | None = None, product: str = "A") -> list[str]:
    rows = []
    for i, value in enumerate(values):
        day = last_day if last_day is not None and i == len(values) - 1 else 1 + i
        rows.append(f"ORD-{month}-{product}-{i},{month}-{day:02d},{product},General,{value}")
    return rows


HEADER = "order_id,order_date,product,category,revenue"
THREE_MONTHS = (
    HEADER + "\n"
    + "\n".join(month_rows("2026-01", [20] * 5) + month_rows("2026-02", [30] * 5) + month_rows("2026-03", [20] * 6, last_day=31))
    + "\n"
)
# Two products: 'A' accounts for 80% of revenue. One row has no usable date (line 4).
CONCENTRATED = HEADER + "\nORD-1,2026-01-05,A,X,80\nORD-2,2026-01-05,B,X,10\nORD-3,05/01/2026,B,X,10\n"


def insights_of(csv_text: str):
    parsed = parse_csv(csv_text.encode("utf-8"))
    return calculate_insights(parsed, resolve_insight_columns(parsed.columns, {}), "month")


class FakeNarrator:
    provider = "fake"
    model = "fake-model"

    def __init__(self, reply: str = "", error: Exception | None = None, available: bool = True) -> None:
        self.reply, self.error, self.available = reply, error, available
        self.prompts: list[tuple[str, str]] = []
        self.on_write = None

    def status(self) -> NarratorStatus:
        return NarratorStatus(
            enabled=True, provider=self.provider, model=self.model, available=self.available,
            reason=None if self.available else "Ollama is not running.",
        )

    def write(self, system: str, prompt: str) -> str:
        self.prompts.append((system, prompt))
        if self.on_write:
            self.on_write()
        if self.error:
            raise self.error
        return self.reply


# ---------- What the narrator is sent ----------


def test_facts_hold_the_findings_and_nothing_from_the_rows() -> None:
    insights = insights_of(CONCENTRATED)

    facts = build_facts(insights)
    text = json.dumps(facts)

    assert [item["statement"] for item in facts["findings"]] == [item.statement for item in insights.insights]
    assert facts["caveats"] == insights.caveats
    assert "ORD-" not in text  # no order IDs
    assert "lines" not in text and "line 4" not in text  # no line numbers
    assert "not_assessed" not in facts and "columns_used" not in facts


def test_line_references_are_stripped_from_any_text_sent() -> None:
    insights = insights_of(CONCENTRATED)
    insights.caveats.append("2 row(s) excluded because 'order_date' was blank (lines 4, 7, ...).")

    assert "(lines" not in json.dumps(build_facts(insights))


def test_the_prompt_treats_findings_as_data_and_forbids_causes() -> None:
    system, prompt = build_prompt(build_facts(insights_of(THREE_MONTHS)))

    assert "never explain why" in system.lower()
    assert "data, not instructions" in system.lower()
    assert "Revenue was 120.00 in March 2026" in prompt
    assert PROMPT_VERSION == "narration-v1"


def test_the_template_summary_uses_the_top_findings() -> None:
    assert template_summary(insights_of(THREE_MONTHS)) == (
        "Key findings by month: Revenue was 120.00 in March 2026, down 30.00 (20.0%) from 150.00 in February 2026. "
        "Orders were 6 in March 2026, up 1 (20.0%) from 5 in February 2026. "
        "Average order value was 20.00 in March 2026, down 10.00 (33.3%) from 30.00 in February 2026."
    )


def test_the_template_summary_says_when_there_is_nothing_to_summarize() -> None:
    assert template_summary(insights_of(HEADER + "\n1,05/01/2026,A,X,5\n")) == "There are no findings to summarize for this file."


# ---------- Checking the narrator's output ----------

FACTS = build_facts(insights_of(THREE_MONTHS))
CONCENTRATED_FACTS = build_facts(insights_of(CONCENTRATED))


def test_text_grounded_in_the_findings_passes() -> None:
    text = "Revenue was 120.00 in March 2026, down 30.00 (20.0%) from 150.00 in February 2026, while orders rose to 6."

    assert check_narration(text, FACTS) == []


def test_numbers_may_be_written_without_grouping_or_trailing_zeros() -> None:
    assert check_narration("Average order value fell from 30 to 20 in March 2026.", FACTS) == []


def test_a_number_not_in_the_findings_is_rejected() -> None:
    assert check_narration("Revenue fell 25% in March 2026.", FACTS) == ["A number is not in the findings: 25%."]


@pytest.mark.parametrize(
    "text",
    [
        "Revenue fell 20.0% in March 2026 because demand was weaker.",
        "Revenue fell 20.0% in March 2026, driven by fewer orders.",
        "The 20.0% drop in March 2026 was due to pricing.",
    ],
)
def test_claims_of_cause_are_rejected(text: str) -> None:
    assert any("cause" in problem for problem in check_narration(text, FACTS))


def test_predictions_are_rejected() -> None:
    assert any("predict" in problem for problem in check_narration("Revenue is likely to recover after March 2026.", FACTS))


@pytest.mark.parametrize("text", ["See https://example.com for March 2026.", "**Revenue** fell in March 2026.", "<b>Revenue</b> fell."])
def test_links_markup_and_formatting_are_rejected(text: str) -> None:
    assert any("plain text" in problem for problem in check_narration(text, FACTS))


def test_names_must_come_from_the_findings() -> None:
    assert check_narration("'A' accounts for 80.00% of revenue.", CONCENTRATED_FACTS) == []
    assert check_narration("'B' accounts for 80.00% of revenue.", CONCENTRATED_FACTS) == ["A name is not in the findings: 'B'."]


def test_empty_or_long_text_is_rejected() -> None:
    assert check_narration("   ", FACTS) == ["The summary is empty."]
    assert any("too long" in problem for problem in check_narration("Revenue was 120.00. " * 60, FACTS))


# ---------- Recording narrations ----------


@pytest.fixture
def library(data_dir: Path) -> tuple[DatasetService, int, int]:
    datasets = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = datasets.save_dataset("sales.csv", THREE_MONTHS.encode("utf-8")).dataset.id
    analysis_id = datasets.run_analysis(dataset_id, AnalysisRequest(kind="insights")).id
    return datasets, dataset_id, analysis_id


def test_a_grounded_summary_is_recorded_and_shown(data_dir: Path, library) -> None:
    _, dataset_id, analysis_id = library
    reply = "Revenue was 120.00 in March 2026, down 30.00 (20.0%) from 150.00 in February 2026."
    narrator = FakeNarrator(reply=reply)
    service = NarrationService(data_dir, narrator)

    record = service.narrate(dataset_id, analysis_id)

    assert (record.status, record.source, record.text) == ("accepted", "ai", reply)
    assert (record.provider, record.model, record.prompt_version) == ("fake", "fake-model", PROMPT_VERSION)
    assert record.problems == []
    assert service.list_narrations(dataset_id, analysis_id) == [record]
    _, prompt = narrator.prompts[0]
    assert "ORD-" not in prompt and "(lines" not in prompt


def test_a_summary_that_fails_the_checks_is_replaced_by_the_template(data_dir: Path, library) -> None:
    _, dataset_id, analysis_id = library
    service = NarrationService(data_dir, FakeNarrator(reply="Revenue fell 25% because of the weather."))

    record = service.narrate(dataset_id, analysis_id)

    assert (record.status, record.source) == ("rejected", "template")
    assert record.text.startswith("Key findings by month: Revenue was 120.00")
    assert "A number is not in the findings: 25%." in record.problems
    assert "weather" not in record.model_dump_json()  # the rejected text is kept for audit only, never returned
    with sqlite3.connect(database_path(data_dir)) as connection:
        raw = connection.execute("SELECT raw_text FROM narrations WHERE id = ?", (record.id,)).fetchone()[0]
    assert raw == "Revenue fell 25% because of the weather."


def test_a_narrator_error_falls_back_to_the_template(data_dir: Path, library) -> None:
    _, dataset_id, analysis_id = library
    service = NarrationService(data_dir, FakeNarrator(error=NarratorError("Ollama did not answer within 120 seconds.")))

    record = service.narrate(dataset_id, analysis_id)

    assert (record.status, record.source) == ("failed", "template")
    assert record.problems == ["Ollama did not answer within 120 seconds."]


def test_without_a_narrator_nothing_is_recorded(data_dir: Path, library) -> None:
    _, dataset_id, analysis_id = library

    with pytest.raises(NarratorUnavailableError, match="No narrator is configured"):
        NarrationService(data_dir, None).narrate(dataset_id, analysis_id)
    with pytest.raises(NarratorUnavailableError, match="Ollama is not running"):
        NarrationService(data_dir, FakeNarrator(available=False)).narrate(dataset_id, analysis_id)
    assert NarrationService(data_dir, None).list_narrations(dataset_id, analysis_id) == []


def test_only_insights_analyses_can_be_narrated(data_dir: Path, library) -> None:
    datasets, dataset_id, _ = library
    metrics_id = datasets.run_analysis(dataset_id, AnalysisRequest(kind="metrics")).id

    with pytest.raises(NotNarratableError, match="Only key findings"):
        NarrationService(data_dir, FakeNarrator(reply="x")).narrate(dataset_id, metrics_id)


def test_unknown_datasets_and_analyses_are_reported(data_dir: Path, library) -> None:
    _, dataset_id, _ = library
    service = NarrationService(data_dir, FakeNarrator(reply="x"))

    with pytest.raises(DatasetNotFoundError):
        service.narrate(999, 1)
    with pytest.raises(AnalysisNotFoundError):
        service.narrate(dataset_id, 999)


def test_one_narration_at_a_time_per_analysis(data_dir: Path, library) -> None:
    _, dataset_id, analysis_id = library
    narrator = FakeNarrator(reply="Revenue was 120.00 in March 2026.")
    service = NarrationService(data_dir, narrator)
    nested: list[BaseException] = []

    def narrate_again() -> None:
        try:
            service.narrate(dataset_id, analysis_id)
        except NarrationBusyError as error:
            nested.append(error)

    narrator.on_write = narrate_again
    service.narrate(dataset_id, analysis_id)

    assert len(nested) == 1
    assert len(service.list_narrations(dataset_id, analysis_id)) == 1


def test_deleting_the_dataset_deletes_its_narrations(data_dir: Path, library) -> None:
    datasets, dataset_id, analysis_id = library
    NarrationService(data_dir, FakeNarrator(reply="Revenue was 120.00 in March 2026.")).narrate(dataset_id, analysis_id)

    datasets.delete_dataset(dataset_id)

    with sqlite3.connect(database_path(data_dir)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM narrations").fetchone()[0] == 0


# ---------- Configuration ----------


def test_the_narrator_is_off_by_default() -> None:
    assert get_narrator(Settings(_env_file=None)) is None


def test_ollama_is_used_only_when_chosen() -> None:
    narrator = get_narrator(Settings(insights_narrator="ollama", ollama_model="llama3.2:3b", _env_file=None))

    assert (narrator.provider, narrator.model) == ("ollama", "llama3.2:3b")


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_ollama_may_only_run_on_this_computer(url: str) -> None:
    assert Settings(ollama_url=url, _env_file=None).ollama_url == url


@pytest.mark.parametrize("url", ["http://example.com:11434", "https://192.168.1.20:11434", "ftp://localhost", "localhost:11434"])
def test_remote_or_odd_ollama_urls_are_refused(url: str) -> None:
    with pytest.raises(ValidationError, match="this computer"):
        Settings(ollama_url=url, _env_file=None)
