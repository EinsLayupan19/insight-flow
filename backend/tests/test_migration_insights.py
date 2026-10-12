"""Migration 0004 (insights analyses) applied to a database created before it existed.

The database is built with migrations 0001-0003 only, filled with real profile, metrics,
trends, and performance history, and then opened by the current code, exactly as an
existing installation would be.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.analytics.product_performance import calculate_product_performance, resolve_performance_columns
from app.analytics.retail_metrics import calculate_retail_metrics, resolve_columns
from app.analytics.sales_trends import calculate_sales_trends, resolve_trend_columns
from app.datasets.models import AnalysisRequest, InsightsAnalysis
from app.datasets.service import DatasetService
from app.ingestion.csv_parser import parse_csv
from app.ingestion.profiler import profile_csv
from app.storage.database import MIGRATIONS_DIR, database_path, load_migrations, open_database, schema_version
from app.storage.file_store import FileStore, sha256_of
from app.storage.repository import DatasetRepository

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = (FIXTURES / "catalog_sales.csv").read_bytes()
MESSY = (FIXTURES / "messy_sales.csv").read_bytes()
VERSION_3 = ("0001_create_datasets_and_analyses.sql", "0002_allow_trends_analyses.sql", "0003_allow_performance_analyses.sql")


def version_3_migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations_v3"
    directory.mkdir()
    for name in VERSION_3:
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
def version_3_library(tmp_path: Path, data_dir: Path) -> dict[str, object]:
    """A schema-version-3 library: profile, metrics, trends, and performance history, plus a deleted dataset."""
    connection = open_database(database_path(data_dir), migrations_dir=version_3_migrations(tmp_path))
    assert schema_version(connection) == 3
    repo = DatasetRepository(connection)

    dataset_id = save_dataset(repo, data_dir, "catalog_sales.csv", CATALOG)
    parsed = parse_csv(CATALOG)
    results = {
        "profile": (profile_csv(parsed), {}),
        "metrics": (calculate_retail_metrics(parsed, resolve_columns(parsed.columns, {})), {"column_mapping": {}}),
        "trends": (
            calculate_sales_trends(parsed, resolve_trend_columns(parsed.columns, {}), "week"),
            {"column_mapping": {}, "grain": "week"},
        ),
        "performance": (
            calculate_product_performance(parsed, resolve_performance_columns(parsed.columns, {})),
            {"column_mapping": {}},
        ),
    }
    ids = {}
    for day, (kind, (result, parameters)) in enumerate(results.items(), start=2):
        ids[kind] = repo.insert_analysis(
            dataset_id=dataset_id, kind=kind, parameters=parameters, result_json=result.model_dump_json(),
            app_version="0.1.0", created_at=f"2026-01-0{day}T00:00:00.000+00:00",
        )

    deleted = save_dataset(repo, data_dir, "messy_sales.csv", MESSY)
    deleted_analysis_id = repo.insert_analysis(
        dataset_id=deleted, kind="profile", parameters={}, result_json=profile_csv(parse_csv(MESSY)).model_dump_json(),
        app_version="0.1.0", created_at="2026-01-07T00:00:00.000+00:00",
    )
    repo.delete_dataset(deleted)
    connection.close()
    return {
        "dataset_id": dataset_id,
        "ids": ids,
        "results": {kind: result for kind, (result, _) in results.items()},
        "deleted_analysis_id": deleted_analysis_id,
    }


def test_upgrading_keeps_every_earlier_kind_readable(data_dir: Path, version_3_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")  # opening the database applies 0004
    dataset_id = version_3_library["dataset_id"]
    ids = version_3_library["ids"]

    history = service.list_analyses(dataset_id)

    assert [entry.kind for entry in history] == ["performance", "trends", "metrics", "profile"]
    for kind, analysis_id in ids.items():
        record = service.get_analysis(dataset_id, analysis_id)
        assert record.kind == kind
        assert record.result == version_3_library["results"][kind]
    with sqlite3.connect(database_path(data_dir)) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    # Upgraded through 0004 and on to the newest migration, whichever that is.
    assert versions == list(range(1, len(load_migrations()) + 1))


def test_upgraded_database_records_insights_next_to_the_old_history(data_dir: Path, version_3_library: dict) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = version_3_library["dataset_id"]

    insights = service.run_analysis(dataset_id, AnalysisRequest(kind="insights"))

    assert isinstance(insights, InsightsAnalysis)
    assert service.list_analyses(dataset_id)[0].kind == "insights"
    assert insights.id > version_3_library["deleted_analysis_id"]  # ids of deleted analyses are never reused


def test_upgraded_schema_keeps_its_rules(data_dir: Path, version_3_library: dict) -> None:
    DatasetService(data_dir, app_version="9.9.9").list_datasets()  # apply 0004
    connection = open_database(database_path(data_dir))
    dataset_id = version_3_library["dataset_id"]
    insert = (
        "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
        " VALUES (?, ?, '{}', '{}', '0.1.0', '2026-01-08T00:00:00+00:00')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(insert, (dataset_id, "chat"))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(insert, (999, "insights"))
    indexes = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "analyses_by_dataset" in indexes
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    connection.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    connection.close()


def test_a_new_database_accepts_every_analysis_kind(data_dir: Path) -> None:
    service = DatasetService(data_dir, app_version="9.9.9")
    dataset_id = service.save_dataset("catalog_sales.csv", CATALOG).dataset.id

    for kind in ("profile", "metrics", "trends", "performance", "insights"):
        service.run_analysis(dataset_id, AnalysisRequest(kind=kind))

    assert [entry.kind for entry in service.list_analyses(dataset_id)][0] == "insights"
    assert len(service.list_analyses(dataset_id)) == 5
