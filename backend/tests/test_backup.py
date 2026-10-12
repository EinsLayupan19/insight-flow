"""Backups of the dataset library (SQLite database + stored CSV files), their verification, and restores.

Every test builds its own library in a temporary directory; nothing here touches backend/data.
"""

import hashlib
import json
import os
import shutil
import signal
import sqlite3
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.datasets.models import AnalysisRequest
from app.datasets.service import DatasetService
from app.storage import backup
from app.storage.backup import BackupError, create_backup, prune_backups, restore_backup, verify_backup
from app.storage.database import MIGRATIONS_DIR, database_path, open_database

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "sample_sales.csv").read_bytes()
CATALOG = (FIXTURES / "catalog_sales.csv").read_bytes()
NOON = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def library(data_dir: Path) -> Path:
    """A library with two datasets and some analysis history."""
    service = DatasetService(data_dir, app_version="9.9.9")
    first = service.save_dataset("sample_sales.csv", SAMPLE).dataset.id
    second = service.save_dataset("catalog_sales.csv", CATALOG).dataset.id
    service.run_analysis(first, AnalysisRequest(kind="profile"))
    service.run_analysis(first, AnalysisRequest(kind="trends", grain="week"))
    service.run_analysis(second, AnalysisRequest(kind="performance"))
    return data_dir


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def table(path: Path, name: str) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()  # fixed table names only
    finally:
        connection.close()


def tree_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# ---------- Creating a backup ----------


def test_backup_holds_the_database_and_every_stored_file(library: Path, destination: Path) -> None:
    result = create_backup(library, destination, now=NOON)

    assert result.path == destination / "insightflow-backup-20261013T120000Z"
    assert sorted(path.name for path in (result.path / "uploads").iterdir()) == sorted(
        path.name for path in (library / "uploads").iterdir()
    )
    for stored in (library / "uploads").iterdir():
        assert (result.path / "uploads" / stored.name).read_bytes() == stored.read_bytes()
    for name in ("datasets", "analyses", "schema_migrations"):
        assert table(result.path / "insightflow.db", name) == table(database_path(library), name)
    assert (result.datasets, result.files, result.problems) == (2, 2, [])


def test_backup_never_changes_the_live_library(library: Path, destination: Path) -> None:
    before = tree_hashes(library)

    create_backup(library, destination, now=NOON)

    assert tree_hashes(library) == before


def test_manifest_and_checksums_describe_every_file(library: Path, destination: Path) -> None:
    path = create_backup(library, destination, now=NOON).path

    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "insightflow-backup"
    assert manifest["created_at"] == "2026-10-13T12:00:00Z"
    assert manifest["schema_version"] == len(list(MIGRATIONS_DIR.glob("*.sql")))
    assert manifest["database"]["integrity_check"] == "ok"
    assert {entry["file"] for entry in manifest["uploads"]} == {f"uploads/{p.name}" for p in (path / "uploads").iterdir()}

    # SHA256SUMS uses the `sha256sum -c` format: "<hex>  <relative path>", one file per line.
    listed = {}
    for line in (path / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    on_disk = tree_hashes(path)
    del on_disk["SHA256SUMS"]
    assert listed == on_disk


def test_the_database_copy_is_a_consistent_snapshot(library: Path, destination: Path) -> None:
    """An uncommitted write in progress is not in the backup (SQLite's online backup copies committed data)."""
    writer = sqlite3.connect(database_path(library), isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("DELETE FROM analyses")
        path = create_backup(library, destination, now=NOON).path
        writer.execute("ROLLBACK")
    finally:
        writer.close()

    assert len(table(path / "insightflow.db", "analyses")) == 3


def test_missing_and_changed_stored_files_are_reported_and_not_copied(library: Path, destination: Path) -> None:
    sample, catalog = sorted((library / "uploads").iterdir(), key=lambda p: p.stat().st_size)
    sample.unlink()
    catalog.write_bytes(catalog.read_bytes() + b"tampered\n")

    result = create_backup(library, destination, now=NOON)

    assert result.files == 0
    assert len(result.problems) == 2
    assert any("missing" in problem for problem in result.problems)
    assert any("changed" in problem for problem in result.problems)
    assert not (result.path / "uploads").exists() or not any((result.path / "uploads").iterdir())
    verify_backup(result.path)  # still a valid backup of what could be saved, with the problems recorded


def test_files_without_a_dataset_are_left_out(library: Path, destination: Path) -> None:
    (library / "uploads" / ("0" * 64 + ".csv")).write_bytes(b"orphan\n")
    (library / "uploads" / "partial.csv.123.tmp").write_bytes(b"half")

    result = create_backup(library, destination, now=NOON)

    assert result.files == 2
    assert result.unreferenced_files == 2


def test_an_existing_backup_is_never_overwritten(library: Path, destination: Path) -> None:
    first = create_backup(library, destination, now=NOON).path
    before = tree_hashes(first)

    with pytest.raises(BackupError, match="already exists"):
        create_backup(library, destination, now=NOON)

    assert tree_hashes(first) == before


def test_a_failed_backup_leaves_nothing_behind(library: Path, destination: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "_write_checksums", broken)

    with pytest.raises(OSError, match="disk full"):
        create_backup(library, destination, now=NOON)

    assert list(destination.iterdir()) == []


def test_refuses_a_data_directory_without_a_database(tmp_path: Path, destination: Path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(BackupError, match="No InsightFlow database"):
        create_backup(tmp_path / "empty", destination, now=NOON)

    assert not (tmp_path / "empty" / "insightflow.db").exists()  # a backup never creates a database


def test_refuses_to_store_backups_inside_the_data_directory(library: Path) -> None:
    with pytest.raises(BackupError, match="outside DATA_DIR"):
        create_backup(library, library / "backups", now=NOON)


def test_an_empty_library_can_be_backed_up(data_dir: Path, destination: Path) -> None:
    open_database(database_path(data_dir)).close()

    result = create_backup(data_dir, destination, now=NOON)

    assert (result.datasets, result.files) == (0, 0)
    verify_backup(result.path)


# ---------- Verifying a backup ----------


def tamper_upload(path: Path) -> None:
    upload = next((path / "uploads").iterdir())
    upload.write_bytes(upload.read_bytes().replace(b",", b";", 1))


def tamper_database(path: Path) -> None:
    connection = sqlite3.connect(path / "insightflow.db")
    connection.execute("UPDATE datasets SET filename = 'renamed.csv'")
    connection.commit()
    connection.close()


def tamper_manifest(path: Path) -> None:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = 99
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "tamper",
    [
        tamper_upload,
        tamper_database,
        tamper_manifest,
        lambda path: next((path / "uploads").iterdir()).unlink(),
        lambda path: (path / "uploads" / ("f" * 64 + ".csv")).write_bytes(b"extra\n"),
        lambda path: (path / "notes.txt").write_text("extra"),
        lambda path: (path / "SHA256SUMS").write_text("", encoding="utf-8"),
    ],
    ids=["changed upload", "changed database", "changed manifest", "missing upload", "extra upload", "extra file", "empty checksums"],
)
def test_verification_detects_any_change(library: Path, destination: Path, tamper) -> None:
    path = create_backup(library, destination, now=NOON).path
    verify_backup(path)

    tamper(path)

    with pytest.raises(BackupError):
        verify_backup(path)


def test_verification_detects_a_dataset_that_was_left_out(library: Path, destination: Path) -> None:
    """Even when the checksums were rewritten to match, every dataset needs its file or a recorded problem."""
    path = create_backup(library, destination, now=NOON).path
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    dropped = manifest["uploads"].pop()
    (path / dropped["file"]).unlink()
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "SHA256SUMS").unlink()
    backup._write_checksums(path)

    with pytest.raises(BackupError, match="neither a stored file nor a recorded problem"):
        verify_backup(path)


def test_checksums_cannot_point_outside_the_backup(library: Path, destination: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    outside = destination / "outside.txt"
    outside.write_text("x")
    digest = hashlib.sha256(b"x").hexdigest()
    with (path / "SHA256SUMS").open("a", encoding="utf-8") as sums:
        sums.write(f"{digest}  ../outside.txt\n")

    with pytest.raises(BackupError, match="unexpected path"):
        verify_backup(path)


# ---------- Restoring ----------


def test_restore_rebuilds_a_working_library(library: Path, destination: Path, tmp_path: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    target = tmp_path / "restored"

    restore_backup(path, target)

    original = DatasetService(library, app_version="9.9.9")
    restored = DatasetService(target, app_version="9.9.9")
    assert restored.list_datasets() == original.list_datasets()
    for dataset in original.list_datasets():
        assert restored.list_analyses(dataset.id) == original.list_analyses(dataset.id)
        assert restored.get_dataset(dataset.id).file_stored
        restored.run_analysis(dataset.id, AnalysisRequest(kind="metrics"))  # reads and re-hashes the stored file


def test_restore_into_an_existing_empty_directory(library: Path, destination: Path, tmp_path: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    (tmp_path / "restored").mkdir()

    restore_backup(path, tmp_path / "restored")

    assert tree_hashes(tmp_path / "restored")["insightflow.db"] == tree_hashes(path)["insightflow.db"]


def test_restore_never_overwrites_existing_data(library: Path, destination: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    before = tree_hashes(library)

    with pytest.raises(BackupError, match="not empty"):
        restore_backup(path, library)

    assert tree_hashes(library) == before


def test_restore_refuses_a_changed_backup(library: Path, destination: Path, tmp_path: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    tamper_upload(path)

    with pytest.raises(BackupError):
        restore_backup(path, tmp_path / "restored")

    assert not (tmp_path / "restored").exists()
    assert [p.name for p in tmp_path.iterdir() if "restoring" in p.name] == []


def test_restore_refuses_a_backup_from_a_newer_version(data_dir: Path, destination: Path, tmp_path: Path) -> None:
    newer = tmp_path / "newer_migrations"
    shutil.copytree(MIGRATIONS_DIR, newer)
    count = len(list(newer.glob("*.sql")))
    (newer / f"{count + 1:04d}_future_change.sql").write_text("CREATE TABLE future (id INTEGER);\n", encoding="utf-8")
    open_database(database_path(data_dir), migrations_dir=newer).close()
    path = create_backup(data_dir, destination, now=NOON).path

    with pytest.raises(BackupError, match="newer"):
        restore_backup(path, tmp_path / "restored")


def test_a_restored_library_keeps_the_recorded_problems(library: Path, destination: Path, tmp_path: Path) -> None:
    missing = next((library / "uploads").iterdir())
    missing.unlink()
    path = create_backup(library, destination, now=NOON).path

    restore_backup(path, tmp_path / "restored")

    restored = DatasetService(tmp_path / "restored", app_version="9.9.9")
    stored = sorted(restored.get_dataset(dataset.id).file_stored for dataset in restored.list_datasets())
    assert stored == [False, True]  # the dataset whose file was already missing is restored as missing


# ---------- Command line ----------


def test_command_line_round_trip(library: Path, destination: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert backup.main(["create", "--data-dir", str(library), "--dest", str(destination)]) == 0
    (created,) = destination.iterdir()
    assert str(created) in capsys.readouterr().out

    assert backup.main(["verify", str(created)]) == 0
    assert backup.main(["restore", str(created), "--target", str(tmp_path / "restored")]) == 0

    tamper_upload(created)
    assert backup.main(["verify", str(created)]) == 1
    assert "Backup check failed" in capsys.readouterr().err


def test_command_line_reports_problems_with_exit_code_2(library: Path, destination: Path) -> None:
    next((library / "uploads").iterdir()).unlink()

    assert backup.main(["create", "--data-dir", str(library), "--dest", str(destination)]) == 2


def test_an_incomplete_backup_verifies_and_restores_with_exit_code_2(
    library: Path, destination: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Valid (every file matches its checksum) but incomplete: distinct from both success and failure."""
    next((library / "uploads").iterdir()).unlink()
    path = create_backup(library, destination, now=NOON).path
    capsys.readouterr()

    assert backup.main(["verify", str(path)]) == 2
    assert backup.main(["restore", str(path), "--target", str(tmp_path / "restored")]) == 2
    output = capsys.readouterr()
    assert "every file matches its checksum" in output.out
    assert "INCOMPLETE: 1 dataset(s)" in output.err
    assert (tmp_path / "restored" / "insightflow.db").is_file()  # restored, with the dataset marked missing


# ---------- Restore integrity: only verified bytes are restored ----------


def change_after_verification(monkeypatch: pytest.MonkeyPatch, change) -> None:
    """Let the restore verify the backup, then change the backup before anything is copied."""
    real_verify = backup._verify

    def verify_then_change(path: Path):
        verified = real_verify(path)
        change(path)
        return verified

    monkeypatch.setattr(backup, "_verify", verify_then_change)


def replace_upload(path: Path) -> None:
    upload = next((path / "uploads").iterdir())
    replacement = upload.with_name("replacement.tmp")
    replacement.write_bytes(b"order_id,quantity\nFORGED,1\n")
    os.replace(replacement, upload)  # a different file under the same name


@pytest.mark.parametrize(
    "change",
    [tamper_upload, replace_upload, tamper_database],
    ids=["upload edited in place", "upload replaced", "database edited"],
)
def test_a_backup_changed_after_verification_is_not_restored(
    library: Path, destination: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change
) -> None:
    path = create_backup(library, destination, now=NOON).path
    change_after_verification(monkeypatch, change)
    target = tmp_path / "restored"

    with pytest.raises(BackupError, match="changed after the backup was checked"):
        restore_backup(path, target)

    assert not target.exists()
    assert [entry.name for entry in tmp_path.iterdir() if "restoring" in entry.name] == []


def test_restore_refuses_a_symlink_target(library: Path, destination: Path, tmp_path: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    (tmp_path / "elsewhere").mkdir()
    try:
        os.symlink(tmp_path / "elsewhere", tmp_path / "link", target_is_directory=True)
    except OSError:
        pytest.skip("creating symbolic links needs extra privileges on this system")

    with pytest.raises(BackupError, match="not empty"):
        restore_backup(path, tmp_path / "link")


@pytest.mark.parametrize("where", ["uploads/" + "e" * 64 + ".csv", "uploads"])
def test_symbolic_links_inside_a_backup_are_refused(library: Path, destination: Path, tmp_path: Path, where: str) -> None:
    path = create_backup(library, destination, now=NOON).path
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.csv").write_text("secret")
    if where == "uploads":
        shutil.move(path / "uploads", outside / "uploads")
    try:
        os.symlink(outside / ("uploads" if where == "uploads" else "secret.csv"), path / where, target_is_directory=where == "uploads")
    except OSError:
        pytest.skip("creating symbolic links needs extra privileges on this system")

    with pytest.raises(BackupError, match="symbolic link"):
        verify_backup(path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes need a POSIX system")
def test_special_files_inside_a_backup_are_refused(library: Path, destination: Path) -> None:
    path = create_backup(library, destination, now=NOON).path
    os.mkfifo(path / "uploads" / ("d" * 64 + ".csv"))

    with pytest.raises(BackupError, match="not a regular file"):
        verify_backup(path)


# ---------- Malformed manifests ----------


def rewrite_manifest(path: Path, change) -> None:
    """Change the manifest and recompute SHA256SUMS, so only the manifest's content is wrong."""
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    changed = change(manifest)
    (path / "manifest.json").write_text(json.dumps(manifest if changed is None else changed), encoding="utf-8")
    (path / "SHA256SUMS").unlink()
    backup._write_checksums(path)


MALFORMED = {
    "uploads entry is a string": lambda m: m.__setitem__("uploads", ["x"]),
    "database is a string": lambda m: m.__setitem__("database", "x"),
    "problem dataset_id is a list": lambda m: m.__setitem__("problems", [{"dataset_id": [1], "file": "a" * 64 + ".csv", "reason": "missing"}]),
    "manifest is a list": lambda m: [],
    "uploads is an object": lambda m: m.__setitem__("uploads", {}),
    "format_version is true": lambda m: m.__setitem__("format_version", True),
    "datasets is negative": lambda m: m.__setitem__("datasets", -1),
    "schema_version is text": lambda m: m.__setitem__("schema_version", "5"),
    "upload without sha256": lambda m: m["uploads"][0].pop("sha256"),
    "upload file outside uploads/": lambda m: m["uploads"][0].__setitem__("file", "../" + m["uploads"][0]["file"]),
    "unknown problem reason": lambda m: m.__setitem__("problems", [{"dataset_id": 9, "file": "a" * 64 + ".csv", "reason": "lost"}]),
    "dataset listed twice": lambda m: m.__setitem__("problems", [{"dataset_id": m["uploads"][0]["dataset_id"], "file": "a" * 64 + ".csv", "reason": "missing"}]),
    "missing key": lambda m: m.pop("unreferenced_files"),
}


@pytest.mark.parametrize("change", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_manifest_is_a_clean_error(
    library: Path, destination: Path, tmp_path: Path, capsys: pytest.CaptureFixture, change
) -> None:
    path = create_backup(library, destination, now=NOON).path
    rewrite_manifest(path, change)
    capsys.readouterr()

    with pytest.raises(BackupError):
        verify_backup(path)
    assert backup.main(["verify", str(path)]) == 1
    assert backup.main(["restore", str(path), "--target", str(tmp_path / "restored")]) == 1
    errors = capsys.readouterr().err
    assert "Traceback" not in errors and "manifest.json" in errors
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("name", ["manifest.json", "SHA256SUMS"])
def test_files_that_are_not_utf8_are_a_clean_error(library: Path, destination: Path, name: str) -> None:
    path = create_backup(library, destination, now=NOON).path
    (path / name).write_bytes(b"\xff\xfe not text")
    if name == "manifest.json":
        (path / "SHA256SUMS").unlink()
        backup._write_checksums(path)

    with pytest.raises(BackupError):
        verify_backup(path)
    assert backup.main(["verify", str(path)]) == 1


# ---------- Disk space and interrupted runs ----------


DiskUsage = namedtuple("DiskUsage", "total used free")


def test_a_backup_that_would_fill_the_disk_is_not_started(library: Path, destination: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda path: DiskUsage(total=10**9, used=96 * 10**7, free=4 * 10**7))

    with pytest.raises(BackupError, match="Not enough free space"):
        create_backup(library, destination, now=NOON)

    assert list(destination.iterdir()) == []


def test_a_backup_stopped_by_sigterm_leaves_nothing_behind(
    library: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """systemd stops a job with SIGTERM (for example after its timeout): the unfinished folder is removed."""
    real_write = backup._write_checksums

    def stopped_midway(directory: Path) -> None:
        real_write(directory)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)  # what the signal would run

    monkeypatch.setattr(backup, "_write_checksums", stopped_midway)

    with pytest.raises(SystemExit) as stopped:
        backup.main(["create", "--data-dir", str(library), "--dest", str(destination)])

    assert stopped.value.code == 128 + signal.SIGTERM
    assert list(destination.iterdir()) == []
    assert signal.getsignal(signal.SIGTERM) is not None  # the previous handler is restored afterwards


# ---------- Retention (prune) ----------


def make_backups(library: Path, destination: Path, times: list[datetime]) -> list[Path]:
    return [create_backup(library, destination, now=moment).path for moment in times]


def names(paths) -> list[str]:
    return sorted(Path(path).name for path in paths)


def listing(folder: Path) -> list[str]:
    """What is in the folder, apart from the lock file a prune --apply leaves (harmless, and reused)."""
    return names(entry for entry in folder.iterdir() if entry.name != backup.PRUNE_LOCK)


def backup_folders(folder: Path) -> list[Path]:
    return [entry for entry in folder.iterdir() if entry.name.startswith(backup.BACKUP_PREFIX)]


def days_back(count: int, hour: int = 3) -> list[datetime]:
    return [datetime(2026, 10, 13, hour, tzinfo=UTC) - timedelta(days=offset) for offset in range(count)]


def test_prune_previews_by_default_and_deletes_nothing(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(5))

    plan = prune_backups(destination, keep_daily=2, keep_monthly=0)

    assert names(plan.delete) == names(made[2:])  # the three oldest days
    assert not plan.applied
    assert listing(destination) == names(made)


def test_prune_apply_keeps_recent_days_and_months(library: Path, destination: Path) -> None:
    daily = make_backups(library, destination, days_back(20))  # 2026-09-24 .. 2026-10-13
    older = make_backups(library, destination, [datetime(2026, 8, 1, 3, tzinfo=UTC), datetime(2026, 8, 20, 3, tzinfo=UTC),
                                                datetime(2026, 7, 5, 3, tzinfo=UTC)])

    plan = prune_backups(destination, keep_daily=14, keep_monthly=3, apply=True)

    # 14 days (Sep 30 .. Oct 13). Monthly: the newest of October and of September are already among them, so the
    # third month adds the newest of August. July is outside the three most recent months.
    kept = listing(destination)
    assert kept == names([*daily[:14], older[1]])
    assert names(plan.delete) == names([*daily[14:], older[0], older[2]])
    for path in backup_folders(destination):
        verify_backup(path)  # what is left is intact


def test_several_backups_on_one_day_count_as_one_day(library: Path, destination: Path) -> None:
    same_day = make_backups(library, destination, [datetime(2026, 10, 13, hour, tzinfo=UTC) for hour in (1, 2, 3)])
    yesterday = make_backups(library, destination, days_back(2)[1:])

    plan = prune_backups(destination, keep_daily=2, keep_monthly=0)

    assert names(plan.keep) == names([same_day[2], yesterday[0]])


def test_prune_never_deletes_the_newest_backup_that_verifies_cleanly(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(6))
    for broken in made[:3]:  # the three newest are damaged
        tamper_upload(broken)

    plan = prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names(made[:4])  # damaged ones are kept for inspection, and the clean one
    assert "newest backup that verifies cleanly" in plan.keep[made[3]]
    assert names(plan.damaged) == names(made[:3])


def test_an_incomplete_backup_is_not_counted_as_clean(library: Path, destination: Path) -> None:
    complete = make_backups(library, destination, days_back(3)[1:])
    next((library / "uploads").iterdir()).unlink()
    incomplete = make_backups(library, destination, days_back(1))

    plan = prune_backups(destination, keep_daily=1, keep_monthly=0)

    assert "newest backup that verifies cleanly" in plan.keep[complete[0]]
    assert incomplete[0] in plan.keep


def test_prune_refuses_when_no_backup_verifies(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(3))
    for broken in made:
        tamper_upload(broken)

    with pytest.raises(BackupError, match="nothing was deleted"):
        prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names(made)


def test_prune_only_touches_backup_folders(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(3))
    (destination / "notes.txt").write_text("mine")
    (destination / "insightflow-backup-manual-copy").mkdir()
    (destination / "insightflow-backup-20200101T000000Z.tar.gz").write_bytes(b"archive")

    prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names([made[0], "notes.txt", "insightflow-backup-manual-copy",
                                                  "insightflow-backup-20200101T000000Z.tar.gz"])


def test_prune_removes_only_old_unfinished_folders(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(1))
    old = destination / f".insightflow-backup-20261001T030000Z.partial-{'0' * 32}"
    fresh = destination / f".insightflow-backup-20261013T030000Z.partial-{'1' * 32}"
    for folder in (old, fresh):
        folder.mkdir()
        (folder / "insightflow.db").write_bytes(b"half")
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old, (two_days_ago, two_days_ago))

    preview = prune_backups(destination, keep_daily=1, keep_monthly=0)
    assert preview.stale_partials == [old] and old.exists()  # a preview removes nothing

    prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)
    assert listing(destination) == names([made[0], fresh])  # a run still in progress is left alone


@pytest.mark.parametrize("keep_daily, keep_monthly", [(0, 12), (-1, 0), (14, -1)])
def test_prune_needs_a_sensible_policy(destination: Path, keep_daily: int, keep_monthly: int) -> None:
    destination.mkdir()

    with pytest.raises(BackupError, match="Keep at least 1 daily backup"):
        prune_backups(destination, keep_daily=keep_daily, keep_monthly=keep_monthly)


def test_prune_command_line(library: Path, destination: Path, capsys: pytest.CaptureFixture) -> None:
    made = make_backups(library, destination, days_back(3))
    capsys.readouterr()

    assert backup.main(["prune", "--dest", str(destination), "--keep-daily", "1", "--keep-monthly", "0"]) == 0
    preview = capsys.readouterr().out
    assert f"KEEP    {made[0].name}" in preview and f"DELETE  {made[2].name}" in preview
    assert "Preview only: nothing was deleted" in preview
    assert len(listing(destination)) == 3

    assert backup.main(["prune", "--dest", str(destination), "--keep-daily", "1", "--keep-monthly", "0", "--apply"]) == 0
    assert f"DELETED {made[2].name}" in capsys.readouterr().out
    assert listing(destination) == names(made[:1])

    assert backup.main(["prune", "--dest", str(destination), "--keep-daily", "0"]) == 1


# ---------- Retention with a dataset whose stored file is missing ----------


def test_old_incomplete_backups_are_pruned_once_a_clean_one_is_kept(library: Path, destination: Path) -> None:
    """A stored file goes missing after one clean backup; nightly backups are then valid but incomplete."""
    clean = create_backup(library, destination, now=datetime(2026, 8, 1, 3, tzinfo=UTC)).path
    next((library / "uploads").iterdir()).unlink()  # the source file disappears
    incomplete = make_backups(library, destination, days_back(30))  # 2026-09-14 .. 2026-10-13

    plan = prune_backups(destination, keep_daily=14, keep_monthly=12, apply=True)

    # 14 days (Sep 30 .. Oct 13, which also hold the newest of October and September), and the clean one: the
    # newest backup that verifies cleanly (also August's newest). Sep 14 .. Sep 29 are outside every window.
    assert listing(destination) == names([*incomplete[:14], clean])
    assert "newest backup that verifies cleanly" in plan.keep[clean]
    assert names(plan.delete) == names(incomplete[14:])  # old incomplete backups outside the windows
    assert names(plan.incomplete) == names(incomplete)
    for path in backup_folders(destination):
        verify_backup(path)  # what is left is intact (clean or valid-but-incomplete)


def test_the_most_recent_valid_backup_is_kept_even_when_incomplete(library: Path, destination: Path) -> None:
    clean = create_backup(library, destination, now=datetime(2026, 8, 1, 3, tzinfo=UTC)).path
    next((library / "uploads").iterdir()).unlink()
    incomplete = make_backups(library, destination, days_back(5))

    prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names([incomplete[0], clean])  # the latest state, and the last clean one


def test_a_damaged_backup_does_not_take_a_valid_backups_place_in_a_window(library: Path, destination: Path) -> None:
    clean = create_backup(library, destination, now=datetime(2026, 8, 1, 3, tzinfo=UTC)).path
    next((library / "uploads").iterdir()).unlink()
    valid, damaged = make_backups(library, destination, [datetime(2026, 10, 13, 1, tzinfo=UTC), datetime(2026, 10, 13, 2, tzinfo=UTC)])
    tamper_database(damaged)

    plan = prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names([valid, damaged, clean])  # damaged kept for inspection, not instead of valid
    assert names(plan.damaged) == names([damaged])


def test_without_any_clean_backup_nothing_is_deleted(library: Path, destination: Path, capsys: pytest.CaptureFixture) -> None:
    """The file was already missing before the first backup: every backup is incomplete."""
    next((library / "uploads").iterdir()).unlink()
    made = make_backups(library, destination, days_back(20))
    capsys.readouterr()

    with pytest.raises(BackupError, match="nothing was deleted"):
        prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names(made)
    assert backup.main(["prune", "--dest", str(destination), "--keep-daily", "1", "--apply"]) == 1
    assert "Repair the dataset" in capsys.readouterr().err  # points the owner at the fix
    assert listing(destination) == names(made)


# ---------- Concurrent and interrupted prunes ----------


def test_a_second_prune_apply_waits_its_turn(library: Path, destination: Path) -> None:
    made = make_backups(library, destination, days_back(3))

    with backup._prune_lock(destination):  # another prune --apply is running
        with pytest.raises(BackupError, match="Another prune"):
            prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)
        preview = prune_backups(destination, keep_daily=1, keep_monthly=0)  # a preview deletes nothing: not blocked

    assert listing(destination) == names(made)
    assert names(preview.delete) == names(made[1:])
    prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)  # the lock is released afterwards
    assert listing(destination) == names(made[:1])


def test_nothing_is_deleted_if_the_clean_backup_changes_before_deletion(
    library: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_backups(library, destination, days_back(4))
    real_plan = backup._plan_prune

    def plan_then_damage(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        tamper_upload(plan.clean)  # the one backup that must survive is damaged meanwhile
        return plan

    monkeypatch.setattr(backup, "_plan_prune", plan_then_damage)

    with pytest.raises(BackupError, match="no longer verifies"):
        prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    assert listing(destination) == names(made)


def test_an_interrupted_deletion_never_leaves_a_half_deleted_backup_under_its_name(
    library: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = make_backups(library, destination, days_back(3))
    real_rmtree = shutil.rmtree

    def stopped(path, *args, **kwargs):
        raise OSError("stopped midway")

    monkeypatch.setattr(backup.shutil, "rmtree", stopped)
    with pytest.raises(OSError, match="stopped midway"):
        prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)

    leftovers = [entry.name for entry in destination.iterdir() if ".deleting-" in entry.name]
    assert len(leftovers) == 1 and made[2].name in leftovers[0]  # renamed first, so no longer a backup name
    assert sorted(path.name for path in backup_folders(destination)) == names(made[:2])

    monkeypatch.setattr(backup.shutil, "rmtree", real_rmtree)
    prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)
    assert listing(destination) == names(made[:1])  # the leftover was removed by the next prune


# ---------- An empty backup folder ----------


def test_prune_apply_on_a_folder_without_backups_says_so_and_deletes_nothing(destination: Path, capsys: pytest.CaptureFixture) -> None:
    destination.mkdir()
    leftover = destination / f".insightflow-backup-20261001T030000Z.partial-{'0' * 32}"  # even stale leftovers stay:
    leftover.mkdir()  # nothing is deleted without a clean backup
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(leftover, (two_days_ago, two_days_ago))

    with pytest.raises(BackupError, match="No backups in .* so nothing was deleted"):
        prune_backups(destination, keep_daily=1, keep_monthly=0, apply=True)
    assert leftover.exists()

    capsys.readouterr()
    assert backup.main(["prune", "--dest", str(destination), "--apply"]) == 1
    error = capsys.readouterr().err
    assert "No backups in" in error and "no longer verifies" not in error
    assert leftover.exists()


def test_prune_preview_on_a_folder_without_backups_says_so(destination: Path, capsys: pytest.CaptureFixture) -> None:
    destination.mkdir()

    assert backup.main(["prune", "--dest", str(destination)]) == 0
    assert "No backups found" in capsys.readouterr().out
