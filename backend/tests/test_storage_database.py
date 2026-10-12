"""Schema migrations and database guarantees (foreign keys, cascade, uniqueness)."""

import sqlite3
import threading
from pathlib import Path

import pytest

from app.config import Settings
from app.storage.database import load_migrations, open_database, schema_version, split_statements

LATEST_VERSION = len(load_migrations())


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row["name"] for row in rows}


def test_new_database_gets_the_full_schema(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "new.db")

    assert {"datasets", "analyses", "schema_migrations"} <= table_names(connection)
    assert schema_version(connection) == LATEST_VERSION
    connection.close()


def test_opening_again_does_not_reapply_migrations(tmp_path: Path) -> None:
    open_database(tmp_path / "db.sqlite").close()
    connection = open_database(tmp_path / "db.sqlite")

    rows = connection.execute("SELECT version, name FROM schema_migrations").fetchall()
    assert [(row["version"], row["name"]) for row in rows] == [
        (1, "create_datasets_and_analyses"),
        (2, "allow_trends_analyses"),
    ]
    connection.close()


def test_threads_opening_a_new_database_at_once_all_succeed(tmp_path: Path) -> None:
    path = tmp_path / "busy.db"
    errors: list[BaseException] = []

    def open_and_close() -> None:
        try:
            open_database(path).close()
        except BaseException as error:  # collected and asserted below
            errors.append(error)

    threads = [threading.Thread(target=open_and_close) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


def insert_dataset(connection: sqlite3.Connection, sha256: str = "a" * 64) -> int:
    cursor = connection.execute(
        "INSERT INTO datasets (filename, sha256, size_bytes, row_count, column_count, columns_json, stored_file,"
        " created_at) VALUES ('sales.csv', ?, 10, 1, 1, '[\"a\"]', 'x.csv', '2026-01-01T00:00:00+00:00')",
        (sha256,),
    )
    return cursor.lastrowid


def insert_analysis(connection: sqlite3.Connection, dataset_id: int) -> None:
    connection.execute(
        "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
        " VALUES (?, 'profile', '{}', '{}', '0.1.0', '2026-01-01T00:00:00+00:00')",
        (dataset_id,),
    )


def test_analyses_must_belong_to_an_existing_dataset(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "db.sqlite")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_analysis(connection, dataset_id=999)
    connection.close()


def test_deleting_a_dataset_deletes_its_analyses(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "db.sqlite")
    dataset_id = insert_dataset(connection)
    insert_analysis(connection, dataset_id)

    connection.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))

    assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    connection.close()


def test_the_same_content_hash_cannot_be_saved_twice(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "db.sqlite")
    insert_dataset(connection, sha256="b" * 64)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_dataset(connection, sha256="b" * 64)
    connection.close()


def test_failed_migration_is_rolled_back_completely(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_first.sql").write_text("CREATE TABLE first (id INTEGER);\n", encoding="utf-8")
    (migrations / "0002_broken.sql").write_text(
        "CREATE TABLE second (id INTEGER);\nTHIS IS NOT SQL;\n", encoding="utf-8"
    )

    with pytest.raises(sqlite3.OperationalError):
        open_database(tmp_path / "db.sqlite", migrations_dir=migrations)

    connection = sqlite3.connect(tmp_path / "db.sqlite")
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    connection.close()
    assert "first" in names
    assert "second" not in names  # the failed migration left nothing behind
    assert versions == [1]


def test_migration_files_must_be_numbered_without_gaps(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "0003_third.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="no gaps"):
        load_migrations(tmp_path)


def test_split_statements_ignores_comments_and_semicolons_inside_them() -> None:
    script = "-- a comment; with a semicolon\nCREATE TABLE a (x TEXT DEFAULT 'semi;colon');\n\nCREATE INDEX b ON a (x);\n-- trailing comment\n"

    statements = split_statements(script)

    assert len(statements) == 2
    assert statements[1] == "CREATE INDEX b ON a (x);"


def test_relative_data_dir_is_resolved_from_the_backend_folder() -> None:
    settings = Settings(data_dir=Path("data"), _env_file=None)

    assert settings.data_dir.is_absolute()
    assert settings.data_dir.parent.name == "backend"
