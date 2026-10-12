"""Writes and records narrations of saved insights analyses.

Every attempt is recorded with its provider, model, and prompt version: accepted text, text that
failed the checks (kept for audit, never shown), or a narrator error. The text shown is the
model's only when it passed every check; otherwise it is the deterministic template summary.
"""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app import __version__
from app.datasets.models import InsightsAnalysis
from app.datasets.service import DatasetNotFoundError, DatasetService
from app.narration.facts import build_facts, template_summary
from app.narration.models import NarrationRecord, NarrationStatus
from app.narration.prompt import PROMPT_VERSION, build_prompt
from app.narration.providers import NOT_CONFIGURED, Narrator, NarratorError
from app.narration.validation import check_narration
from app.storage.database import database_path, open_database, transaction, utc_now

MAX_RAW_CHARACTERS = 4000

_in_flight: set[tuple[str, int]] = set()  # (database, analysis id) being narrated right now
_in_flight_lock = threading.Lock()


class NarratorUnavailableError(Exception):
    """No narrator is configured, or it is not reachable. The message says how to fix it."""


class NotNarratableError(ValueError):
    """Only insights analyses can be narrated."""


class NarrationBusyError(Exception):
    """A narration of this analysis is already running."""


class NarrationService:
    def __init__(self, data_dir: Path, narrator: Narrator | None) -> None:
        self._datasets = DatasetService(data_dir, app_version=__version__)
        self._database_path = database_path(data_dir)
        self._narrator = narrator

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = open_database(self._database_path)
        try:
            yield connection
        finally:
            connection.close()

    def narrate(self, dataset_id: int, analysis_id: int) -> NarrationRecord:
        """Ask the narrator to summarize a saved insights analysis, check the text, and record the attempt."""
        record = self._datasets.get_analysis(dataset_id, analysis_id)  # DatasetNotFoundError, AnalysisNotFoundError
        if not isinstance(record, InsightsAnalysis):
            raise NotNarratableError(f"Only key findings can be summarized. Analysis {analysis_id} is a {record.kind} analysis.")
        if self._narrator is None:
            raise NarratorUnavailableError(NOT_CONFIGURED)
        status = self._narrator.status()
        if not status.available:
            raise NarratorUnavailableError(status.reason or "The narrator is not available.")

        key = (str(self._database_path), analysis_id)
        with _in_flight_lock:
            if key in _in_flight:
                raise NarrationBusyError("A summary of these findings is already being written. Wait for it to finish.")
            _in_flight.add(key)
        try:
            return self._narrate(record)
        finally:
            with _in_flight_lock:
                _in_flight.discard(key)

    def _narrate(self, record: InsightsAnalysis) -> NarrationRecord:
        assert self._narrator is not None
        facts = build_facts(record.result)
        system, prompt = build_prompt(facts)
        template = template_summary(record.result)
        raw: str | None
        status: NarrationStatus
        try:
            raw = self._narrator.write(system, prompt)[:MAX_RAW_CHARACTERS]
        except NarratorError as error:
            raw, status, problems, text = None, "failed", [str(error)], template
        else:
            problems = check_narration(raw, facts)
            status, text = ("accepted", raw.strip()) if not problems else ("rejected", template)

        try:
            with self._connection() as connection, transaction(connection):
                cursor = connection.execute(
                    "INSERT INTO narrations (dataset_id, analysis_id, provider, model, prompt_version, status, text,"
                    " raw_text, problems_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.dataset_id, record.id, self._narrator.provider, self._narrator.model, PROMPT_VERSION,
                        status, text, raw, json.dumps(problems), utc_now(),
                    ),
                )
                narration_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise DatasetNotFoundError(record.dataset_id) from error  # deleted while the narrator was writing
        return next(item for item in self.list_narrations(record.dataset_id, record.id) if item.id == narration_id)

    def list_narrations(self, dataset_id: int, analysis_id: int) -> list[NarrationRecord]:
        """Recorded narrations of an analysis, newest first."""
        self._datasets.get_analysis(dataset_id, analysis_id)  # DatasetNotFoundError, AnalysisNotFoundError
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM narrations WHERE dataset_id = ? AND analysis_id = ? ORDER BY created_at DESC, id DESC",
                (dataset_id, analysis_id),
            ).fetchall()
        return [
            NarrationRecord(
                id=row["id"], dataset_id=row["dataset_id"], analysis_id=row["analysis_id"], created_at=row["created_at"],
                provider=row["provider"], model=row["model"], prompt_version=row["prompt_version"], status=row["status"],
                source="ai" if row["status"] == "accepted" else "template", text=row["text"],
                problems=json.loads(row["problems_json"]),
            )
            for row in rows
        ]
