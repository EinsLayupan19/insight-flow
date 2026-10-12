"""Migration 0005 (narrations) applied to a database created before it existed."""

import shutil
import sqlite3
from pathlib import Path

from app.analytics.insights import calculate_insights, resolve_insight_columns
from app.datasets.service import DatasetService
from app.ingestion.csv_parser import parse_csv
from app.ingestion.profiler import profile_csv
from app.storage.database import MIGRATIONS_DIR, database_path, load_migrations, open_database, schema_version
from app.storage.file_store import FileStore, sha256_of
from app.storage.repository import DatasetRepository

CATALOG = (Path(__file__).parent / "fixtures" / "catalog_sales.csv").read_bytes()


def test_upgrading_a_version_4_library_adds_narrations_and_keeps_the_history(tmp_path: Path, data_dir: Path) -> None:
    migrations = tmp_path / "migrations_v4"
    migrations.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("000[1-4]_*.sql")):
        shutil.copy(path, migrations)
    connection = open_database(database_path(data_dir), migrations_dir=migrations)
    assert schema_version(connection) == 4
    repo = DatasetRepository(connection)
    parsed = parse_csv(CATALOG)
    dataset_id = repo.insert_dataset(
        filename="catalog_sales.csv", sha256=sha256_of(CATALOG), size_bytes=len(CATALOG), row_count=len(parsed.rows),
        columns=parsed.columns, stored_file=FileStore(data_dir / "uploads").save(CATALOG, sha256_of(CATALOG)),
        created_at="2026-01-01T00:00:00.000+00:00",
    )
    insights = calculate_insights(parsed, resolve_insight_columns(parsed.columns, {}), "day")
    for kind, result, parameters in (
        ("profile", profile_csv(parsed), {}),
        ("insights", insights, {"column_mapping": {}, "grain": "day"}),
    ):
        repo.insert_analysis(
            dataset_id=dataset_id, kind=kind, parameters=parameters, result_json=result.model_dump_json(),
            app_version="0.1.0", created_at="2026-01-02T00:00:00.000+00:00",
        )
    connection.close()

    service = DatasetService(data_dir, app_version="9.9.9")  # opening the database applies 0005
    history = service.list_analyses(dataset_id)

    assert {entry.kind for entry in history} == {"profile", "insights"}
    recorded = next(entry for entry in history if entry.kind == "insights")
    assert service.get_analysis(dataset_id, recorded.id).result == insights
    with sqlite3.connect(database_path(data_dir)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert "narrations" in tables
    assert versions == list(range(1, len(load_migrations()) + 1))
