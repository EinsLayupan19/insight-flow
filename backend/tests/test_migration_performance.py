"""Migration 0003 (performance analyses) applied to a database created before it existed.

The database is built with migrations 0001 and 0002 only, filled with real profile, metrics,
and trends history, and then opened by the current code, exactly as an existing installation would be.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.analytics.retail_metrics import calculate_retail_metrics, resolve_columns
from app.analytics.sales_trends import calculate_sales_trends, resolve_trend_columns
from app.datasets.models import AnalysisRequest, MetricsAnalysis, PerformanceAnalysis, ProfileAnalysis, TrendsAnalysis
from app.datasets.service import DatasetService
from app.ingestion.csv_parser import parse_csv
from app.ingestion.profiler import profile_csv
from app.storage.database import MIGRATIONS_DIR, database_path, open_database, schema_version
from app.storage.file_store import FileStore, sha256_of
from app.storage.repository import DatasetRepository

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = (FIXTURES / "catalog_sales.csv").read_bytes()
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()


def version_2_migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations_v2"
    directory.mkdir()
    for name in ("0001_create_datasets_and_analyses.sql", "0002_allow_trends_analyses.sql"):
        shutil.copy(MIGRATIONS_DIR / name, directory)
    return directory


def save_dataset(repo: DatasetRepository, data_dir: Path, filename: str, content: bytes) -> int:
    parsed = parse_csv(content)
    stored = FileStore(data_dir / "uploads").save(content, sha256_of(content))
    return repo.insert_dataset(
        filename=filename, sha256=sha256_of(content), size_bytes=len(content), row_count=len(parsed.rows),
        columns=parsed.columns, stored_file=stored, created_at="2026-01-01T00:00:00.000+00:00",
    )


@pytest.fixture
def version_2_library(tmp_path: Path, data_dir: Path) -> dict[str, object]:
    """A schema-version-2 library: profile, metrics, and trends history, plus a deleted dataset."""
    connection = open_database(database_path(data_dir), migrations_dir=version_2_migrations(tmp_path))
    assert schema_version(connection) == 2
    repo = DatasetRepository(connection)

    dataset_id = save_dataset(repo, data_dir, "catalog_sales.csv", CATALOG)
    parsed = parse_csv(CATALOG)
    results = {
        "profile": profile_csv(parsed),
        "metrics": calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {})),
        "trends": calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "week"),
    }
    parameters = {"profile": {}, "metrics": {"column_mapping": {}}, "trends": {"column_mapping": {}, "grain": "week"}}
    ids = {}
    for day, kind in enumerate(("profile", "metrics", "trends"), start=2):
        ids[kind] = repo.insert_analysis(
            dataset_id=dataset_id, kind=kind, parameters=parameters[kind], result_json=results[kind].model_dump_json(),
            app_version="0.1.0", created_at=f"2026-01-0{day}T00:00:00.000+00:00",
        )

    # A deleted dataset leaves the analyses id counter ahead of the highest remaining id.
    deleted = save_dataset(repo, data_dir, "messy_sales.csv", MESSY)
    deleted_analysis_id = repo.insert_analysis(
        dataset_id=deleted, kind="profile", parameters={}, result_json=profile_csv(parse_csv(MESSY)).model_dump_json(),
        app_version="0.1.0", created_at="2026-01-06T00:00:00.000+00:00",
    )
    repo.delete_dataset(deleted)
    connection.close()
    return {"dataset_id": dataset_id, "ids": ids, "results": results, "deleted_analysis_id": deleted_analysis_id}


def test_upgrading_keeps_profile_metrics_and_trends_history_readable(data_dir: Path, version_2_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")  # opening the database applies 0003
    dataset_id = version_2_library["dataset_id"]
    ids = version_2_library["ids"]

    history = service.list_analyses(dataset_id)
    profile = service.get_analysis(dataset_id, ids["profile"])
    metrics = service.get_analysis(dataset_id, ids["metrics"])
    trends = service.get_analysis(dataset_id, ids["trends"])

    assert [(entry.id, entry.kind) for entry in history] == [
        (ids["trends"], "trends"),
        (ids["metrics"], "metrics"),
        (ids["profile"], "profile"),
    ]
    assert isinstance(profile, ProfileAnalysis) and profile.result == version_2_library["results"]["profile"]
    assert isinstance(metrics, MetricsAnalysis) and metrics.result == version_2_library["results"]["metrics"]
    assert isinstance(trends, TrendsAnalysis) and trends.result == version_2_library["results"]["trends"]
    assert trends.grain == "week"
    with sqlite3.connect(database_path(data_dir)) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [1, 2, 3]


def test_upgraded_database_records_performance_next_to_the_old_history(data_dir: Path, version_2_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = version_2_library["dataset_id"]

    performance = service.run_analysis(dataset_id, AnalysisRequest(kind="performance"))

    assert isinstance(performance, PerformanceAnalysis)
    assert [entry.kind for entry in service.list_analyses(dataset_id)] == ["performance", "trends", "metrics", "profile"]
    # The id counter carried over: an id used by a deleted analysis is never handed out again.
    assert performance.id > version_2_library["deleted_analysis_id"]


def test_upgraded_schema_keeps_its_rules(data_dir: Path, version_2_library: dict) -> None:
    DatasetService(data_dir, app_version="9.9.9").list_datasets()  # apply 0003
    connection = open_database(database_path(data_dir))
    dataset_id = version_2_library["dataset_id"]
    insert = (
        "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
        " VALUES (?, ?, '{}', '{}', '0.1.0', '2026-01-07T00:00:00+00:00')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(insert, (dataset_id, "profit"))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(insert, (999, "performance"))
    indexes = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "analyses_by_dataset" in indexes
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    connection.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))  # cascade still deletes history
    assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    connection.close()


def test_upgrading_a_version_2_library_without_any_analyses(tmp_path: Path, data_dir: Path) -> None:
    connection = open_database(database_path(data_dir), migrations_dir=version_2_migrations(tmp_path))
    dataset_id = save_dataset(DatasetRepository(connection), data_dir, "catalog_sales.csv", CATALOG)
    connection.close()

    service = DatasetService(data_dir, app_version="9.9.9")
    record = service.run_analysis(dataset_id, AnalysisRequest(kind="performance"))

    assert record.id == 1
    assert service.list_analyses(dataset_id)[0].kind == "performance"


def test_a_new_database_accepts_every_analysis_kind(data_dir: Path) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = service.save_dataset("catalog_sales.csv", CATALOG).dataset.id

    for kind in ("profile", "metrics", "trends", "performance"):
        service.run_analysis(dataset_id, AnalysisRequest(kind=kind))

    assert [entry.kind for entry in service.list_analyses(dataset_id)] == ["performance", "trends", "metrics", "profile"]
