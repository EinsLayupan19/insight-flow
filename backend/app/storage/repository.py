"""SQL for saved datasets and their analysis history.

Only data access lives here; the rules (duplicates, validation, file storage) are in
app/datasets/service.py. Every value is passed as a query parameter.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.storage.database import transaction


@dataclass(frozen=True)
class DatasetRow:
    id: int
    filename: str
    sha256: str
    size_bytes: int
    row_count: int
    column_count: int
    columns: list[str]
    stored_file: str
    created_at: str
    analysis_count: int
    last_analyzed_at: str | None


@dataclass(frozen=True)
class AnalysisRow:
    id: int
    dataset_id: int
    kind: str
    parameters: dict[str, Any]
    result_json: str
    app_version: str
    created_at: str


# Datasets with how many analyses they have and when the latest one ran.
_DATASETS_WITH_HISTORY = """
    SELECT d.id, d.filename, d.sha256, d.size_bytes, d.row_count, d.column_count, d.columns_json,
           d.stored_file, d.created_at,
           COUNT(a.id) AS analysis_count, MAX(a.created_at) AS last_analyzed_at
    FROM datasets AS d
    LEFT JOIN analyses AS a ON a.dataset_id = d.id
"""


class DatasetRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    # ---------- Datasets ----------

    def insert_dataset(
        self,
        *,
        filename: str,
        sha256: str,
        size_bytes: int,
        row_count: int,
        columns: list[str],
        stored_file: str,
        created_at: str,
    ) -> int:
        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO datasets (filename, sha256, size_bytes, row_count, column_count, columns_json,"
                " stored_file, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (filename, sha256, size_bytes, row_count, len(columns), json.dumps(columns), stored_file, created_at),
            )
        return _row_id(cursor)

    def get_dataset(self, dataset_id: int) -> DatasetRow | None:
        row = self._db.execute(f"{_DATASETS_WITH_HISTORY} WHERE d.id = ? GROUP BY d.id", (dataset_id,)).fetchone()
        return _dataset(row) if row else None

    def find_dataset_by_sha256(self, sha256: str) -> DatasetRow | None:
        row = self._db.execute(f"{_DATASETS_WITH_HISTORY} WHERE d.sha256 = ? GROUP BY d.id", (sha256,)).fetchone()
        return _dataset(row) if row else None

    def list_datasets(self) -> list[DatasetRow]:
        rows = self._db.execute(f"{_DATASETS_WITH_HISTORY} GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC")
        return [_dataset(row) for row in rows]

    def delete_dataset(self, dataset_id: int) -> bool:
        """Delete a dataset and (through ON DELETE CASCADE) its analyses. False if it did not exist."""
        with transaction(self._db):
            cursor = self._db.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        return cursor.rowcount > 0

    # ---------- Analyses ----------

    def insert_analysis(
        self,
        *,
        dataset_id: int,
        kind: str,
        parameters: dict[str, Any],
        result_json: str,
        app_version: str,
        created_at: str,
    ) -> int:
        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO analyses (dataset_id, kind, parameters_json, result_json, app_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (dataset_id, kind, json.dumps(parameters), result_json, app_version, created_at),
            )
        return _row_id(cursor)

    def list_analyses(self, dataset_id: int) -> list[AnalysisRow]:
        """A dataset's analyses, newest first."""
        rows = self._db.execute(
            "SELECT * FROM analyses WHERE dataset_id = ? ORDER BY created_at DESC, id DESC", (dataset_id,)
        )
        return [_analysis(row) for row in rows]

    def get_analysis(self, dataset_id: int, analysis_id: int) -> AnalysisRow | None:
        row = self._db.execute(
            "SELECT * FROM analyses WHERE id = ? AND dataset_id = ?", (analysis_id, dataset_id)
        ).fetchone()
        return _analysis(row) if row else None


def _row_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not report the id of the inserted row.")
    return cursor.lastrowid


def _dataset(row: sqlite3.Row) -> DatasetRow:
    return DatasetRow(
        id=row["id"],
        filename=row["filename"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        row_count=row["row_count"],
        column_count=row["column_count"],
        columns=json.loads(row["columns_json"]),
        stored_file=row["stored_file"],
        created_at=row["created_at"],
        analysis_count=row["analysis_count"],
        last_analyzed_at=row["last_analyzed_at"],
    )


def _analysis(row: sqlite3.Row) -> AnalysisRow:
    return AnalysisRow(
        id=row["id"],
        dataset_id=row["dataset_id"],
        kind=row["kind"],
        parameters=json.loads(row["parameters_json"]),
        result_json=row["result_json"],
        app_version=row["app_version"],
        created_at=row["created_at"],
    )
