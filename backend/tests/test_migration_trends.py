"""Migration 0002 (trends analyses) applied to a database created before it existed.

The database is built with migration 0001 only, filled with real profile and metrics
history, and then opened by the current code, exactly as an existing installation would be.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.analytics.retail_metrics import calculate_retail_metrics, resolve_columns
from app.datasets.models import AnalysisRequest, MetricsAnalysis, ProfileAnalysis, TrendsAnalysis
from app.datasets.service import DatasetService
from app.ingestion.csv_parser import parse_csv
from app.ingestion.profiler import profile_csv
from app.storage.database import MIGRATIONS_DIR, database_path, open_database, schema_version
from app.storage.file_store import FileStore, sha256_of
from app.storage.repository import DatasetRepository

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "sample_sales.csv").read_bytes()
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()


def version_1_migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations_v1"
    directory.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0001_create_datasets_and_analyses.sql", directory)
    return directory


def save_v1_dataset(repo: DatasetRepository, data_dir: Path, filename: str, content: bytes) -> int:
    parsed = parse_csv(content)
    stored = FileStore(data_dir / "uploads").save(content, sha256_of(content))
    return repo.insert_dataset(
        filename=filename, sha256=sha256_of(content), size_bytes=len(content), row_count=len(parsed.rows),
        columns=parsed.columns, stored_file=stored, created_at="2026-01-01T00:00:00.000+00:00",
    )


@pytest.fixture
def version_1_library(tmp_path: Path, data_dir: Path) -> dict[str, object]:
    """A schema-version-1 library: one dataset with profile and metrics history, plus a deleted one."""
    connection = open_database(database_path(data_dir), migrations_dir=version_1_migrations(tmp_path))
    assert schema_version(connection) == 1
    repo = DatasetRepository(connection)

    dataset_id = save_v1_dataset(repo, data_dir, "sample_sales.csv", SAMPLE)
    parsed = parse_csv(SAMPLE)
    profile = profile_csv(parsed)
    metrics = calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {}))
    profile_id = repo.insert_analysis(
        dataset_id=dataset_id, kind="profile", parameters={}, result_json=profile.model_dump_json(),
        app_version="0.1.0", created_at="2026-01-02T00:00:00.000+00:00",
    )
    metrics_id = repo.insert_analysis(
        dataset_id=dataset_id, kind="metrics", parameters={"column_mapping": {"quantity": "quantity"}},
        result_json=metrics.model_dump_json(), app_version="0.1.0", created_at="2026-01-03T00:00:00.000+00:00",
    )

    # A deleted dataset leaves the analyses id counter ahead of the highest remaining id.
    deleted = save_v1_dataset(repo, data_dir, "messy_sales.csv", MESSY)
    deleted_analysis_id = repo.insert_analysis(
        dataset_id=deleted, kind="profile", parameters={}, result_json=profile_csv(parse_csv(MESSY)).model_dump_json(),
        app_version="0.1.0", created_at="2026-01-04T00:00:00.000+00:00",
    )
    repo.delete_dataset(deleted)
    connection.close()
    return {
        "dataset_id": dataset_id,
        "profile_id": profile_id,
        "metrics_id": metrics_id,
        "deleted_analysis_id": deleted_analysis_id,
        "profile": profile,
        "metrics": metrics,
    }


def test_upgrading_keeps_profile_and_metrics_history_readable(data_dir: Path, version_1_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")  # opening the database applies 0002
    dataset_id = version_1_library["dataset_id"]

    history = service.list_analyses(dataset_id)
    profile = service.get_analysis(dataset_id, version_1_library["profile_id"])
    metrics = service.get_analysis(dataset_id, version_1_library["metrics_id"])

    assert [(entry.id, entry.kind) for entry in history] == [
        (version_1_library["metrics_id"], "metrics"),
        (version_1_library["profile_id"], "profile"),
    ]
    assert isinstance(profile, ProfileAnalysis)
    assert profile.result == version_1_library["profile"]
    assert profile.app_version == "0.1.0"
    assert isinstance(metrics, MetricsAnalysis)
    assert metrics.result == version_1_library["metrics"]
    assert metrics.column_mapping == {"quantity": "quantity"}
    assert service.get_dataset(dataset_id).analysis_count == 2
    with sqlite3.connect(database_path(data_dir)) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2


def test_upgraded_database_records_trends_next_to_the_old_history(data_dir: Path, version_1_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = version_1_library["dataset_id"]

    trends = service.run_analysis(dataset_id, AnalysisRequest(kind="trends", grain="day"))

    assert isinstance(trends, TrendsAnalysis)
    assert [entry.kind for entry in service.list_analyses(dataset_id)] == ["trends", "metrics", "profile"]
    # The id counter carried over: an id used by a deleted analysis is never handed out again.
    assert trends.id > version_1_library["deleted_analysis_id"]


def test_upgraded_schema_keeps_its_rules(data_dir: Path, version_1_library: dict) -> None:
    DatasetService(data_dir, app_version="9.9.9").list_datasets()  # apply 0002
    connection = open_database(database_path(data_dir))
    dataset_id = version_1_library["dataset_id"]

    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
            " VALUES (?, 'profit', '{}', '{}', '0.1.0', '2026-01-05T00:00:00+00:00')",
            (dataset_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(
            "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
            " VALUES (999, 'trends', '{}', '{}', '0.1.0', '2026-01-05T00:00:00+00:00')"
        )
    indexes = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "analyses_by_dataset" in indexes
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    connection.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))  # cascade still deletes history
    assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    connection.close()


def test_upgrading_a_library_without_any_analyses(tmp_path: Path, data_dir: Path) -> None:
    connection = open_database(database_path(data_dir), migrations_dir=version_1_migrations(tmp_path))
    dataset_id = save_v1_dataset(DatasetRepository(connection), data_dir, "sample_sales.csv", SAMPLE)
    connection.close()

    service = DatasetService(data_dir, app_version="9.9.9")
    record = service.run_analysis(dataset_id, AnalysisRequest(kind="trends"))

    assert record.id == 1
    assert service.list_analyses(dataset_id)[0].kind == "trends"


def test_a_new_database_accepts_every_analysis_kind(data_dir: Path) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = service.save_dataset("sample_sales.csv", SAMPLE).dataset.id

    for request in (AnalysisRequest(kind="profile"), AnalysisRequest(kind="metrics"), AnalysisRequest(kind="trends")):
        service.run_analysis(dataset_id, request)

    assert [entry.kind for entry in service.list_analyses(dataset_id)] == ["trends", "metrics", "profile"]
