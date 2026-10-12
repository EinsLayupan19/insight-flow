"""Production settings: API docs, readiness, and DuckDB resource limits."""

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analytics import duckdb_loader
from app.analytics.duckdb_loader import load_into_duckdb
from app.config import Settings
from app.ingestion.csv_parser import parse_csv
from app.main import create_app
from app.storage.database import load_migrations

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_sales.csv").read_bytes()


def settings(tmp_path: Path, **values) -> Settings:
    return Settings(data_dir=tmp_path / "data", _env_file=None, **values)


# ---------- API docs ----------


def test_api_docs_are_available_outside_production(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path, app_env="development")))

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_api_docs_are_off_in_production(tmp_path: Path) -> None:
    # Production requires an explicit host list (see test_host_headers.py); TestClient sends "testserver".
    client = TestClient(create_app(settings(tmp_path, app_env="production", allowed_hosts="testserver")))

    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path
    assert client.get("/api/health").status_code == 200  # the API itself is unaffected


# ---------- Readiness ----------


def test_ready_when_the_database_opens_and_the_data_directory_is_writable(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "uploads").mkdir(parents=True)
    keep = data_dir / "uploads" / "keep.csv"
    keep.write_bytes(b"a\n1\n")

    response = TestClient(create_app(settings(tmp_path))).get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "data_dir": "ok"},
        "schema_version": len(load_migrations()),
    }
    assert keep.read_bytes() == b"a\n1\n"  # user files are never touched
    assert sorted(path.name for path in data_dir.iterdir()) == ["insightflow.db", "uploads"]  # probe file removed


def test_not_ready_when_the_data_directory_is_not_usable(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("not a directory")  # DATA_DIR points at a file

    response = TestClient(create_app(settings(tmp_path))).get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["data_dir"] == "The data directory is not writable."
    assert str(tmp_path) not in response.text  # no server paths in the answer


def test_not_ready_when_the_database_cannot_be_opened(tmp_path: Path) -> None:
    (tmp_path / "data" / "insightflow.db").mkdir(parents=True)  # a directory where the database file should be

    response = TestClient(create_app(settings(tmp_path))).get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "The database could not be opened."
    assert str(tmp_path) not in response.text


# ---------- DuckDB limits ----------


def test_duckdb_limits_have_conservative_defaults() -> None:
    defaults = Settings(_env_file=None)

    assert (defaults.duckdb_threads, defaults.duckdb_memory_limit) == (2, "1GB")


@pytest.mark.parametrize(
    "values",
    [
        {"duckdb_threads": 0},
        {"duckdb_threads": 65},
        {"duckdb_memory_limit": "lots"},
        {"duckdb_memory_limit": "-1GB"},
        {"duckdb_memory_limit": "32MB"},  # below 64 MB even loading a small file fails
    ],
)
def test_invalid_duckdb_limits_are_refused(values: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def use_settings(monkeypatch: pytest.MonkeyPatch, configured: Settings) -> None:
    monkeypatch.setattr(duckdb_loader, "get_settings", lambda: configured)


def test_every_analysis_connection_uses_the_configured_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, settings(tmp_path, duckdb_threads=3, duckdb_memory_limit="256MB"))
    expected = duckdb.connect(":memory:", config={"memory_limit": "256MB"}).execute("SELECT current_setting('memory_limit')").fetchone()[0]

    with load_into_duckdb(parse_csv(SAMPLE)) as table:
        threads, memory = table.connection.execute("SELECT current_setting('threads'), current_setting('memory_limit')").fetchone()

    assert threads == 3
    assert memory == expected


def test_the_memory_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass the 64 MB floor in Settings to prove DuckDB really applies the configured value.
    configured = settings(tmp_path, duckdb_threads=1).model_copy(update={"duckdb_memory_limit": "16MB"})
    use_settings(monkeypatch, configured)

    with pytest.raises(duckdb.OutOfMemoryException), load_into_duckdb(parse_csv(SAMPLE)) as table:
        table.connection.execute(
            "SELECT COUNT(DISTINCT v) FROM (SELECT md5(range::VARCHAR) || md5((range * 7)::VARCHAR) AS v FROM range(1000000))"
        ).fetchall()


def test_duckdb_prints_no_progress_bar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, settings(tmp_path))

    with load_into_duckdb(parse_csv(SAMPLE)) as table:
        enabled = table.connection.execute("SELECT current_setting('enable_progress_bar')").fetchone()[0]

    assert enabled is False


def test_spilled_data_stays_in_the_per_request_temporary_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, settings(tmp_path))
    monkeypatch.chdir(tmp_path)  # DuckDB's default spill directory is ".tmp" under the working directory

    with load_into_duckdb(parse_csv(SAMPLE)) as table:
        spill = Path(table.connection.execute("SELECT current_setting('temp_directory')").fetchone()[0])
        assert spill.exists() and spill.is_dir()

    assert not spill.exists()  # removed with the request's temporary directory
    assert not (tmp_path / ".tmp").exists()


def test_running_out_of_memory_returns_a_clear_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import uploads

    def out_of_memory(*args, **kwargs):
        raise duckdb.OutOfMemoryException("Out of Memory Error: could not allocate block")

    monkeypatch.setattr(uploads, "calculate_retail_metrics", out_of_memory)

    response = TestClient(create_app(settings(tmp_path))).post(
        "/api/uploads/csv/metrics", files={"file": ("s.csv", SAMPLE, "text/csv")}
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "This file needs more memory to analyze than the server allows (DUCKDB_MEMORY_LIMIT). "
        "Try a smaller file, or ask the administrator to raise the limit."
    )
