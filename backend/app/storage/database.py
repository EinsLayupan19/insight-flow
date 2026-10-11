"""SQLite database for saved datasets and their analysis history.

SQLite is built into Python, so this needs no extra package or server. DuckDB stays
the analytics engine; this database only holds small records (dataset metadata and
analysis results) where uniqueness checks, foreign keys, and transactions matter.

The schema lives in numbered SQL files in app/storage/migrations/ (0001_*.sql,
0002_*.sql, ...). `open_database()` applies every migration that has not run yet,
each in its own transaction, and records it in the schema_migrations table, so a
new database and an older one end up with the same schema.

Create or upgrade the database explicitly with:  python -m app.storage.database
"""

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DATABASE_FILENAME = "insightflow.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_MIGRATION_FILE = re.compile(r"(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql")
_migration_lock = threading.Lock()  # threads of this process apply migrations one at a time


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: list[str]


def database_path(data_dir: Path) -> Path:
    return data_dir / DATABASE_FILENAME


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def open_database(path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> sqlite3.Connection:
    """Open the database (creating it if needed) with its schema up to date. The caller closes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: no hidden transactions. Writes use transaction() below.
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")  # SQLite leaves foreign keys off unless asked
    try:
        migrate(connection, load_migrations(migrations_dir))
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in one write transaction: COMMIT if it succeeds, ROLLBACK if anything fails."""
    connection.execute("BEGIN IMMEDIATE")  # take the write lock now, so concurrent writers wait their turn
    try:
        yield connection
    except BaseException:
        # Some errors make SQLite roll back by itself; rolling back again would hide the real error.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def migrate(connection: sqlite3.Connection, migrations: list[Migration]) -> int:
    """Apply pending migrations in order and return the schema version."""
    with _migration_lock:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        current = schema_version(connection)
        for migration in migrations:
            if migration.version <= current:
                continue
            with transaction(connection):
                # Check again inside the lock: another process may have applied it meanwhile.
                done = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (migration.version,)
                ).fetchone()
                if done:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, utc_now()),
                )
        return schema_version(connection)


def schema_version(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_FILE.fullmatch(path.name)
        if not match:
            raise RuntimeError(f"Migration files must be named like 0001_description.sql, not '{path.name}'.")
        statements = split_statements(path.read_text(encoding="utf-8"))
        migrations.append(Migration(int(match["version"]), match["name"], statements))

    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migrations must be numbered 0001, 0002, ... with no gaps or repeats. Found: {versions}")
    return migrations


def split_statements(script: str) -> list[str]:
    """Split a SQL script into statements, using SQLite's own check for a complete statement."""
    statements: list[str] = []
    current = ""
    for line in script.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            statements.append(current.strip())
            current = ""
    leftover = [line for line in current.splitlines() if line.strip() and not line.strip().startswith("--")]
    if leftover:
        raise RuntimeError(f"Migration ends with an incomplete SQL statement: {leftover[0][:80]!r}")
    return statements


def main() -> None:
    """Create or upgrade the database configured by DATA_DIR and report its schema version."""
    from app.config import get_settings  # imported here so the module has no import-time settings

    path = database_path(get_settings().data_dir)
    connection = open_database(path)
    try:
        version = schema_version(connection)
    finally:
        connection.close()
    print(f"Database ready: {path} (schema version {version})")


if __name__ == "__main__":
    main()
