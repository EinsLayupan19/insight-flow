"""The dataset library: saving uploads, running analyses on them, and keeping the history.

What is stored, and where (both under the configured data directory):
- the uploaded file, byte for byte, in uploads/<sha256>.csv on the server's local disk;
- its metadata and every analysis result, in the SQLite database insightflow.db.
Both stay until the dataset is deleted. Nothing is backed up or sent anywhere else.

Rules:
- Duplicates are found by content (SHA-256), not by name: identical content is stored once.
- A file that fails CSV validation is never stored.
- An analysis always runs on the stored copy, after checking it still matches its hash.
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.analytics.retail_metrics import MetricResult, RetailMetrics, calculate_retail_metrics, resolve_columns
from app.datasets.models import (
    AnalysisRequest,
    AnalysisSummary,
    DatasetDetail,
    DatasetSummary,
    MetricsAnalysis,
    MetricsHighlights,
    ProfileAnalysis,
    ProfileHighlights,
    SaveDatasetResponse,
)
from app.ingestion.csv_parser import parse_csv
from app.ingestion.profiler import QualityReport, profile_csv
from app.storage.database import database_path, open_database, utc_now
from app.storage.file_store import FileStore, sha256_of
from app.storage.repository import AnalysisRow, DatasetRepository, DatasetRow

logger = logging.getLogger(__name__)

UPLOADS_DIRNAME = "uploads"
MAX_FILENAME_LENGTH = 255


class DatasetNotFoundError(LookupError):
    def __init__(self, dataset_id: int) -> None:
        super().__init__(f"Dataset {dataset_id} was not found. It may have been deleted.")


class AnalysisNotFoundError(LookupError):
    def __init__(self, dataset_id: int, analysis_id: int) -> None:
        super().__init__(f"Analysis {analysis_id} was not found for dataset {dataset_id}.")


class DatasetService:
    def __init__(self, data_dir: Path, app_version: str) -> None:
        self._database_path = database_path(data_dir)
        self._files = FileStore(data_dir / UPLOADS_DIRNAME)
        self._app_version = app_version

    @contextmanager
    def _repository(self) -> Iterator[DatasetRepository]:
        # One short-lived connection per operation: safe to use from any worker thread.
        connection = open_database(self._database_path)
        try:
            yield DatasetRepository(connection)
        finally:
            connection.close()

    # ---------- Datasets ----------

    def save_dataset(self, filename: str, content: bytes) -> SaveDatasetResponse:
        """Store a validated CSV, or return the existing dataset if the same content was saved before."""
        sha256 = sha256_of(content)
        with self._repository() as repo:
            existing = repo.find_dataset_by_sha256(sha256)
        if existing is not None:
            return SaveDatasetResponse(created=False, dataset=self._detail(existing))

        parsed = parse_csv(content)  # raises CsvValidationError: nothing has been stored yet
        stored_file = self._files.save(content, sha256)
        try:
            with self._repository() as repo:
                dataset_id = repo.insert_dataset(
                    filename=display_name(filename),
                    sha256=sha256,
                    size_bytes=len(content),
                    row_count=len(parsed.rows),
                    columns=parsed.columns,
                    stored_file=stored_file,
                    created_at=utc_now(),
                )
                created = repo.get_dataset(dataset_id)
        except sqlite3.IntegrityError:
            # Another request saved the same content a moment earlier. Its stored file is identical.
            with self._repository() as repo:
                existing = repo.find_dataset_by_sha256(sha256)
            if existing is None:
                raise
            return SaveDatasetResponse(created=False, dataset=self._detail(existing))
        except BaseException:
            self._remove_unreferenced_file(sha256)
            raise

        if created is None:
            raise RuntimeError(f"Dataset {dataset_id} disappeared right after it was saved.")
        return SaveDatasetResponse(created=True, dataset=self._detail(created))

    def list_datasets(self) -> list[DatasetSummary]:
        with self._repository() as repo:
            rows = repo.list_datasets()
        return [_summary(row) for row in rows]

    def get_dataset(self, dataset_id: int) -> DatasetDetail:
        return self._detail(self._dataset_row(dataset_id))

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete the stored file first, then the metadata and history.

        If deleting the records fails afterwards, the dataset stays listed with
        file_stored=false and can simply be deleted again.
        """
        row = self._dataset_row(dataset_id)
        self._files.delete(row.sha256)
        with self._repository() as repo:
            repo.delete_dataset(dataset_id)

    # ---------- Analyses ----------

    def run_analysis(self, dataset_id: int, request: AnalysisRequest) -> ProfileAnalysis | MetricsAnalysis:
        """Analyze the stored file and record the result in the dataset's history."""
        row = self._dataset_row(dataset_id)
        parsed = parse_csv(self._files.read(row.sha256))  # StoredFileError if missing or changed

        result: QualityReport | RetailMetrics
        parameters: dict[str, Any]
        if request.kind == "profile":
            result = profile_csv(parsed)
            parameters = {}
        else:
            columns = resolve_columns(parsed.columns, dict(request.column_mapping))  # ColumnMappingError
            result = calculate_retail_metrics(parsed, columns)
            parameters = {"column_mapping": request.column_mapping}

        try:
            with self._repository() as repo:
                analysis_id = repo.insert_analysis(
                    dataset_id=dataset_id,
                    kind=request.kind,
                    parameters=parameters,
                    result_json=result.model_dump_json(),
                    app_version=self._app_version,
                    created_at=utc_now(),
                )
                stored = repo.get_analysis(dataset_id, analysis_id)
        except sqlite3.IntegrityError as error:
            raise DatasetNotFoundError(dataset_id) from error  # deleted while the analysis was running
        if stored is None:
            raise AnalysisNotFoundError(dataset_id, analysis_id)
        return _record(stored)

    def list_analyses(self, dataset_id: int) -> list[AnalysisSummary]:
        with self._repository() as repo:
            if repo.get_dataset(dataset_id) is None:
                raise DatasetNotFoundError(dataset_id)
            rows = repo.list_analyses(dataset_id)
        return [_analysis_summary(row) for row in rows]

    def get_analysis(self, dataset_id: int, analysis_id: int) -> ProfileAnalysis | MetricsAnalysis:
        with self._repository() as repo:
            if repo.get_dataset(dataset_id) is None:
                raise DatasetNotFoundError(dataset_id)
            row = repo.get_analysis(dataset_id, analysis_id)
        if row is None:
            raise AnalysisNotFoundError(dataset_id, analysis_id)
        return _record(row)

    # ---------- Helpers ----------

    def _dataset_row(self, dataset_id: int) -> DatasetRow:
        with self._repository() as repo:
            row = repo.get_dataset(dataset_id)
        if row is None:
            raise DatasetNotFoundError(dataset_id)
        return row

    def _detail(self, row: DatasetRow) -> DatasetDetail:
        return DatasetDetail(
            **_summary(row).model_dump(),
            columns=row.columns,
            file_stored=self._files.is_stored(row.sha256, row.size_bytes),
        )

    def _remove_unreferenced_file(self, sha256: str) -> None:
        """After a failed save, delete the stored file unless a dataset row uses it."""
        try:
            with self._repository() as repo:
                in_use = repo.find_dataset_by_sha256(sha256) is not None
            if not in_use:
                self._files.delete(sha256)
        except Exception:
            logger.exception("Could not clean up the stored file %s.csv after a failed save", sha256)


def display_name(filename: str) -> str:
    """The uploaded file's own name, without any folder part a client may have sent."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (name or "upload.csv")[:MAX_FILENAME_LENGTH]


def _summary(row: DatasetRow) -> DatasetSummary:
    return DatasetSummary(
        id=row.id,
        filename=row.filename,
        size_bytes=row.size_bytes,
        row_count=row.row_count,
        column_count=row.column_count,
        sha256=row.sha256,
        created_at=row.created_at,
        analysis_count=row.analysis_count,
        last_analyzed_at=row.last_analyzed_at,
    )


def _record(row: AnalysisRow) -> ProfileAnalysis | MetricsAnalysis:
    common = {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "created_at": row.created_at,
        "app_version": row.app_version,
        "column_mapping": row.parameters.get("column_mapping", {}),
    }
    if row.kind == "profile":
        return ProfileAnalysis(kind="profile", result=QualityReport.model_validate_json(row.result_json), **common)
    return MetricsAnalysis(kind="metrics", result=RetailMetrics.model_validate_json(row.result_json), **common)


def _analysis_summary(row: AnalysisRow) -> AnalysisSummary:
    record = _record(row)
    highlights: ProfileHighlights | MetricsHighlights
    if isinstance(record, ProfileAnalysis):
        report = record.result
        highlights = ProfileHighlights(
            duplicate_row_count=report.duplicate_row_count,
            missing_value_count=sum(column.missing_count for column in report.columns),
            type_mismatch_count=sum(column.mismatch_count for column in report.columns),
        )
    else:
        metrics = [value for _, value in record.result if isinstance(value, MetricResult)]
        calculated = sum(metric.status == "calculated" for metric in metrics)
        highlights = MetricsHighlights(calculated_count=calculated, unavailable_count=len(metrics) - calculated)
    return AnalysisSummary(
        **record.model_dump(include={"id", "dataset_id", "created_at", "app_version", "column_mapping"}),
        kind=record.kind,
        highlights=highlights,
    )
