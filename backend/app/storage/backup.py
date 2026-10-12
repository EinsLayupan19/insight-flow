"""Backups of the dataset library: the SQLite database and the stored CSV files.

    python -m app.storage.backup create --dest /var/backups/insightflow     (DATA_DIR from the settings, or --data-dir)
    python -m app.storage.backup verify /var/backups/insightflow/insightflow-backup-20261013T030000Z
    python -m app.storage.backup restore <backup folder> --target /var/lib/insightflow-restored
    python -m app.storage.backup prune --dest /var/backups/insightflow [--keep-daily 14] [--keep-monthly 12] [--apply]

A backup is a folder named insightflow-backup-<UTC time> holding:
    insightflow.db         a snapshot made with SQLite's online backup API
    uploads/<sha256>.csv   the stored file of every dataset in that snapshot, re-hashed while it is copied
    manifest.json          counts, the schema version, and every dataset whose file could not be copied
    SHA256SUMS             the hash of every file above (also checkable with `sha256sum -c SHA256SUMS`)

Consistency: the database is copied first, in one read transaction, so the copy holds only committed data and
is safe to take while the app runs. Stored files are named after the SHA-256 of their content and are never
changed in place, so copying the files the snapshot refers to afterwards gives a matching set. A file that is
missing or changed on disk, or deleted between the two steps, is not copied: it is listed in manifest.json, and
after a restore that dataset shows "Missing or changed", as it would have in the app.

What the checksums prove: SHA-256 detects accidental damage (a bad disk, an interrupted copy, a stray edit) and
every file is checked against them before it is trusted. They do not prove who made a backup: anyone who can
write to a backup folder can change files and recompute SHA256SUMS. Tamper resistance needs a copy the server
cannot change (offline or write-once storage) or a signature made with a key that is not on the server.

Safety: a backup only reads DATA_DIR (it never creates a database there), refuses to start without enough free
space, is written under a temporary name and renamed when complete, and never overwrites another backup. A
restore checks the backup, refuses symbolic links and special files, copies only bytes that match the checksums
it verified, and only writes into a new or empty folder, never over a library. Old backups are removed only by
`prune --apply` (one at a time per folder), which never removes the newest backup that verifies cleanly.

Exit codes: 0 done and complete; 1 failed (nothing was written, or the backup is not valid); 2 done, but some
datasets' stored files are missing from the backup (create, verify, restore). prune: 0 done, 1 refused or failed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import stat
import sys
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from app import __version__
from app.datasets.service import UPLOADS_DIRNAME
from app.storage.database import DATABASE_FILENAME, database_path, load_migrations

BACKUP_PREFIX = "insightflow-backup-"
BACKUP_FORMAT = "insightflow-backup"
BACKUP_FORMAT_VERSION = 1
MANIFEST = "manifest.json"
CHECKSUMS = "SHA256SUMS"
CHUNK = 1024 * 1024

# Free space a new backup must leave on its disk: 10% of the backup's size (at least 16 MB) on top of the
# backup itself, and never less than 5% of the whole disk, so backups cannot fill the system's disk.
RESERVE_FRACTION = 0.10
RESERVE_MINIMUM = 16 * 1024 * 1024
DISK_FLOOR_FRACTION = 0.05

DEFAULT_KEEP_DAILY = 14
DEFAULT_KEEP_MONTHLY = 12
STALE_PARTIAL_AGE = timedelta(days=1)  # an unfinished folder older than this belongs to a run that was killed
PRUNE_LOCK = ".insightflow-prune.lock"  # in the backup folder; held while a prune --apply runs

_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHECKSUM_LINE = re.compile(r"(?P<digest>[0-9a-f]{64})  (?P<name>.+)")
_UPLOAD_NAME = re.compile(rf"{UPLOADS_DIRNAME}/(?P<sha256>[0-9a-f]{{64}})\.csv")
_BACKUP_NAME = re.compile(rf"{BACKUP_PREFIX}(?P<stamp>[0-9]{{8}}T[0-9]{{6}}Z)")
_PARTIAL_NAME = re.compile(rf"\.{BACKUP_PREFIX}[0-9]{{8}}T[0-9]{{6}}Z\.partial-[0-9a-f]{{32}}")
_DELETING_NAME = re.compile(rf"\.(\.?{BACKUP_PREFIX}[0-9]{{8}}T[0-9]{{6}}Z(\.partial-[0-9a-f]{{32}})?)\.deleting-[0-9a-f]{{32}}")
_PROBLEM_REASONS = {"missing": "is missing", "changed": "changed on disk after it was saved"}


class BackupError(Exception):
    """A backup could not be made, checked, restored, or pruned. The message says why."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    schema_version: int
    datasets: int
    files: int
    problems: list[str]  # datasets whose stored file was missing or changed, so it is not in the backup
    unreferenced_files: int  # files in uploads/ that no dataset uses (left out)


@dataclass(frozen=True)
class _Verified:
    result: BackupResult
    checksums: dict[str, str]  # relative path -> SHA-256 that every later read must match


# ---------- Creating ----------


def create_backup(data_dir: Path, destination: Path, *, now: datetime | None = None) -> BackupResult:
    """Back up the library in `data_dir` into a new folder inside `destination`."""
    data_dir, destination = data_dir.resolve(), destination.resolve()
    source = database_path(data_dir)
    if not source.is_file():
        raise BackupError(f"No InsightFlow database at {source}. Nothing to back up.")
    if destination.is_relative_to(data_dir):
        raise BackupError("Keep backups outside DATA_DIR, so that losing one does not lose the other.")

    created_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    name = BACKUP_PREFIX + created_at.strftime("%Y%m%dT%H%M%SZ")
    final = destination / name
    if final.exists():
        raise BackupError(f"{final} already exists. Backups are never overwritten.")

    destination.mkdir(parents=True, exist_ok=True)
    _check_free_space(destination, _estimated_size(source, data_dir / UPLOADS_DIRNAME))
    staging = destination / f".{name}.partial-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        result = _write_backup(source, data_dir / UPLOADS_DIRNAME, staging, created_at)
        verify_backup(staging)
        os.rename(staging, final)  # fails rather than replacing a backup created meanwhile
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # only this run's unfinished folder
        raise
    return replace(result, path=final)


def _estimated_size(source: Path, uploads: Path) -> int:
    stored = sum(path.stat().st_size for path in uploads.iterdir() if path.is_file()) if uploads.is_dir() else 0
    return source.stat().st_size + stored


def _check_free_space(destination: Path, needed: int) -> None:
    usage = shutil.disk_usage(destination)
    reserve = max(int(needed * RESERVE_FRACTION), RESERVE_MINIMUM)
    floor = int(usage.total * DISK_FLOOR_FRACTION)
    if usage.free - needed - reserve < floor:
        raise BackupError(
            f"Not enough free space in {destination}: this backup needs about {_mb(needed + reserve)} and the disk "
            f"must keep {_mb(floor)} free, but only {_mb(usage.free)} is free. Remove old backups "
            "(prune --apply) or use a bigger disk. Nothing was written."
        )


def _write_backup(source: Path, uploads: Path, staging: Path, created_at: datetime) -> BackupResult:
    snapshot = staging / DATABASE_FILENAME
    _snapshot_database(source, snapshot)
    with closing(_open_read_only(snapshot)) as connection:
        _check_database(connection)
        version = _schema_version(connection)
        datasets = connection.execute("SELECT id, sha256 FROM datasets ORDER BY id").fetchall()
        analyses = connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]

    copied: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for dataset_id, sha256 in datasets:
        file_name = f"{sha256}.csv"
        try:
            content = (uploads / file_name).read_bytes()
        except FileNotFoundError:
            problems.append({"dataset_id": dataset_id, "file": file_name, "reason": "missing"})
            continue
        if hashlib.sha256(content).hexdigest() != sha256:
            problems.append({"dataset_id": dataset_id, "file": file_name, "reason": "changed"})
            continue
        (staging / UPLOADS_DIRNAME).mkdir(exist_ok=True)
        (staging / UPLOADS_DIRNAME / file_name).write_bytes(content)  # the bytes just hashed, not a second read
        copied.append({"file": f"{UPLOADS_DIRNAME}/{file_name}", "sha256": sha256, "size_bytes": len(content), "dataset_id": dataset_id})

    referenced = {f"{sha256}.csv" for _, sha256 in datasets}
    unreferenced = sum(1 for path in uploads.iterdir() if path.is_file() and path.name not in referenced) if uploads.is_dir() else 0

    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_version": __version__,
        "schema_version": version,
        "database": {"file": DATABASE_FILENAME, "sha256": _sha256_file(snapshot), "integrity_check": "ok"},
        "datasets": len(datasets),
        "analyses": analyses,
        "uploads": copied,
        "problems": problems,
        "unreferenced_files": unreferenced,
    }
    (staging / MANIFEST).write_bytes(json.dumps(manifest, indent=2).encode("utf-8") + b"\n")
    _write_checksums(staging)
    return BackupResult(staging, version, len(datasets), len(copied), _describe(problems), unreferenced)


def _snapshot_database(source: Path, snapshot: Path) -> None:
    # Read-only, so the backup can never create or change the live database. backup() copies a consistent
    # state and waits while a writer is committing.
    with closing(_open_read_only(source)) as live, closing(sqlite3.connect(snapshot)) as copy:
        live.backup(copy)


def _write_checksums(directory: Path) -> None:
    lines = [f"{_sha256_file(directory / name)}  {name}\n" for name in _files_in(directory) if name != CHECKSUMS]
    (directory / CHECKSUMS).write_bytes("".join(lines).encode("utf-8"))  # LF endings, as sha256sum expects


# ---------- Checking ----------


def verify_backup(path: Path) -> BackupResult:
    """Check every file against SHA256SUMS and the manifest, and the database's integrity. Raises BackupError."""
    return _verify(path).result


def _verify(path: Path) -> _Verified:
    if not path.is_dir() or not (path / CHECKSUMS).is_file():
        raise BackupError(f"{path} is not an InsightFlow backup (no {CHECKSUMS}).")
    listed = _read_checksums(path)
    on_disk = set(_files_in(path)) - {CHECKSUMS}  # also refuses links and special files
    if set(listed) != on_disk:
        missing, extra = sorted(set(listed) - on_disk), sorted(on_disk - set(listed))
        raise BackupError(f"The files do not match {CHECKSUMS}. Missing: {missing or 'none'}. Not listed: {extra or 'none'}.")
    for name, digest in listed.items():
        if _sha256_file(path / name) != digest:
            raise BackupError(f"{name} does not match its checksum: the backup changed after it was made.")

    manifest = _parse_manifest(path)
    if manifest["database"]["sha256"] != listed.get(DATABASE_FILENAME):
        raise BackupError("The database does not match the manifest.")
    uploads = {entry["file"]: entry for entry in manifest["uploads"]}
    if set(uploads) != {name for name in listed if name not in (DATABASE_FILENAME, MANIFEST)}:
        raise BackupError("The stored files do not match the manifest.")
    for name, entry in uploads.items():
        if listed[name] != entry["sha256"]:
            raise BackupError(f"{name} does not match the hash it is named after.")

    with closing(_open_read_only(path / DATABASE_FILENAME)) as connection:
        _check_database(connection)
        version = _schema_version(connection)
        datasets = _dataset_hashes(connection)
    if version != manifest["schema_version"] or len(datasets) != manifest["datasets"]:
        raise BackupError("The database does not match the manifest.")
    accounted = {entry["dataset_id"]: entry["sha256"] for entry in uploads.values()}
    accounted.update({entry["dataset_id"]: datasets.get(entry["dataset_id"]) for entry in manifest["problems"]})
    if accounted != datasets:
        raise BackupError("Some datasets have neither a stored file nor a recorded problem in this backup.")

    result = BackupResult(path, version, len(datasets), len(uploads), _describe(manifest["problems"]), manifest["unreferenced_files"])
    return _Verified(result, listed)


def _read_checksums(path: Path) -> dict[str, str]:
    try:
        text = _read_small_file(path / CHECKSUMS).decode("utf-8")
    except UnicodeDecodeError as error:
        raise BackupError(f"{CHECKSUMS} is not UTF-8 text.") from error
    listed: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.fullmatch(line)
        if not match:
            raise BackupError(f"{CHECKSUMS} has a line that is not '<sha256>  <file>': {line[:80]!r}")
        name = match["name"]
        if name not in (DATABASE_FILENAME, MANIFEST) and not _UPLOAD_NAME.fullmatch(name):
            raise BackupError(f"{CHECKSUMS} lists an unexpected path: {name[:80]!r}")
        if name in listed:
            raise BackupError(f"{CHECKSUMS} lists {name} twice.")
        listed[name] = match["digest"]
    return listed


def _parse_manifest(path: Path) -> dict[str, Any]:
    """The manifest, after checking the type and shape of every value it holds."""
    try:
        manifest = json.loads(_read_small_file(path / MANIFEST).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise _malformed("it is not valid UTF-8 JSON") from error

    if not isinstance(manifest, dict):
        raise _malformed("it is not a JSON object")
    required = ("format", "format_version", "schema_version", "database", "datasets", "analyses", "uploads", "problems", "unreferenced_files")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise _malformed(f"missing {', '.join(missing)}")
    if manifest["format"] != BACKUP_FORMAT or manifest["format_version"] != BACKUP_FORMAT_VERSION or type(manifest["format_version"]) is not int:
        raise BackupError(f"{MANIFEST} is not an InsightFlow backup manifest (format version {BACKUP_FORMAT_VERSION}).")
    for key in ("schema_version", "datasets", "analyses", "unreferenced_files"):
        _whole_number(manifest[key], key)

    database = manifest["database"]
    if not isinstance(database, dict) or database.get("file") != DATABASE_FILENAME or database.get("integrity_check") != "ok":
        raise _malformed(f'"database" must describe {DATABASE_FILENAME} with integrity_check "ok"')
    _hex_digest(database.get("sha256"), "database.sha256")

    if not isinstance(manifest["uploads"], list) or not isinstance(manifest["problems"], list):
        raise _malformed('"uploads" and "problems" must be lists')
    dataset_ids: list[int] = []
    for index, entry in enumerate(manifest["uploads"]):
        where = f"uploads[{index}]"
        if not isinstance(entry, dict):
            raise _malformed(f"{where} is not an object")
        digest = _hex_digest(entry.get("sha256"), f"{where}.sha256")
        if entry.get("file") != f"{UPLOADS_DIRNAME}/{digest}.csv":
            raise _malformed(f"{where}.file must be {UPLOADS_DIRNAME}/<its sha256>.csv")
        _whole_number(entry.get("size_bytes"), f"{where}.size_bytes")
        dataset_ids.append(_whole_number(entry.get("dataset_id"), f"{where}.dataset_id", minimum=1))
    for index, entry in enumerate(manifest["problems"]):
        where = f"problems[{index}]"
        if not isinstance(entry, dict):
            raise _malformed(f"{where} is not an object")
        dataset_ids.append(_whole_number(entry.get("dataset_id"), f"{where}.dataset_id", minimum=1))
        if not isinstance(entry.get("file"), str) or not re.fullmatch(r"[0-9a-f]{64}\.csv", entry["file"]):
            raise _malformed(f"{where}.file must be <sha256>.csv")
        if entry.get("reason") not in _PROBLEM_REASONS:
            raise _malformed(f"{where}.reason must be one of {sorted(_PROBLEM_REASONS)}")
    if len(dataset_ids) != len(set(dataset_ids)):
        raise _malformed("a dataset is listed more than once")
    return manifest


def _malformed(detail: str) -> BackupError:
    return BackupError(f"{MANIFEST} is malformed ({detail}). This backup cannot be trusted; use another one.")


def _whole_number(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:  # bool is an int subclass, so compare the exact type
        raise _malformed(f"{name} must be a whole number of at least {minimum}")
    return value


def _hex_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise _malformed(f"{name} must be a SHA-256 hex digest")
    return value


def _dataset_hashes(connection: sqlite3.Connection) -> dict[int, str]:
    try:
        return dict(connection.execute("SELECT id, sha256 FROM datasets").fetchall())
    except sqlite3.DatabaseError as error:
        raise BackupError("This is not an InsightFlow database (no datasets table).") from error


def _check_database(connection: sqlite3.Connection) -> None:
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        dangling = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"The database copy cannot be read: {error}") from error
    if integrity != [("ok",)]:
        raise BackupError(f"The database copy failed SQLite's integrity check: {integrity[:3]}")
    if dangling:
        raise BackupError(f"The database copy has {len(dangling)} rows that refer to missing rows.")


def _schema_version(connection: sqlite3.Connection) -> int:
    try:
        return connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
    except sqlite3.DatabaseError as error:
        raise BackupError("This is not an InsightFlow database (no schema_migrations table).") from error


# ---------- Restoring ----------


def restore_backup(backup: Path, target: Path) -> BackupResult:
    """Check `backup`, then copy it into `target`, which must not exist yet or be an empty folder.

    Every file is copied from a fresh read that is hashed while it is written, and must match the checksum that
    was verified a moment before; a backup changed or swapped in between is refused, and nothing is restored.
    """
    verified = _verify(backup)
    checked = verified.result
    known = len(load_migrations())
    if checked.schema_version > known:
        raise BackupError(
            f"This backup was made by a newer InsightFlow (schema version {checked.schema_version}; "
            f"this version knows {known}). Restore it with that version or a later one."
        )
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise BackupError(f"{target} is not empty. A restore only writes into a new or empty folder, never over data.")

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.restoring-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        (staging / UPLOADS_DIRNAME).mkdir()
        for name, digest in verified.checksums.items():
            if name != MANIFEST:
                _copy_verified(backup / name, staging / name, digest)
        with closing(_open_read_only(staging / DATABASE_FILENAME)) as connection:
            _check_database(connection)
        if target.exists():
            target.rmdir()  # empty, checked above
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # only this run's unfinished folder
        raise
    return replace(checked, path=target)


def _copy_verified(source: Path, destination: Path, digest: str) -> None:
    """Copy `source`, refusing it unless the bytes written match `digest`, the checksum verified before."""
    hasher = hashlib.sha256()
    with _open_regular(source) as reader, destination.open("xb") as writer:
        for chunk in iter(lambda: reader.read(CHUNK), b""):
            hasher.update(chunk)
            writer.write(chunk)
    if hasher.hexdigest() != digest:
        raise BackupError(f"{source.name} changed after the backup was checked, so nothing was restored.")


# ---------- Pruning ----------


@dataclass(frozen=True)
class PrunePlan:
    keep: dict[Path, list[str]]  # backup folder -> why it is kept
    delete: list[Path]  # backups outside the retention policy, oldest first
    stale_partials: list[Path]  # unfinished folders of stopped runs, and folders of interrupted deletions
    clean: Path | None = None  # the newest backup that verifies cleanly: never deleted
    damaged: list[Path] = field(default_factory=list)  # newer than `clean` and failing verification: kept for inspection
    incomplete: list[Path] = field(default_factory=list)  # newer than `clean`, valid but missing stored files
    backup_bytes: int = 0
    free_bytes: int = 0
    applied: bool = False


def prune_backups(
    destination: Path,
    *,
    keep_daily: int = DEFAULT_KEEP_DAILY,
    keep_monthly: int = DEFAULT_KEEP_MONTHLY,
    apply: bool = False,
    now: datetime | None = None,
) -> PrunePlan:
    """Work out which backups the retention policy keeps; delete the rest only when `apply` is true.

    Kept: the newest backup that verifies cleanly (complete, every checksum matching), whatever its age; damaged
    backups newer than it (for inspection); and, among the others, the newest backup of each of the `keep_daily`
    most recent days that have backups and of each of the `keep_monthly` most recent months. Valid but incomplete
    backups (a dataset's stored file was missing) follow the windows like any other, so a lasting missing file does
    not stop retention. Windows count days with backups, not calendar days, so a long outage does not age
    everything out. If no backup verifies cleanly, nothing is deleted.

    With `apply`, one prune at a time per folder (a lock), the clean backup is checked again just before deleting,
    and each folder is renamed before it is removed, so an interrupted deletion never leaves a damaged folder under
    a backup's name.
    """
    if keep_daily < 1 or keep_monthly < 0:
        raise BackupError("Keep at least 1 daily backup (--keep-daily 1 or more) and 0 or more monthly backups.")
    if not destination.is_dir():
        raise BackupError(f"{destination} is not a folder.")
    if not apply:
        return _plan_prune(destination, keep_daily, keep_monthly, now)

    with _prune_lock(destination):
        plan = _plan_prune(destination, keep_daily, keep_monthly, now)
        if not plan.keep and not plan.delete:  # no backups at all: no clean one either, so nothing may be deleted
            raise BackupError(
                f"No backups in {destination} (folders named {BACKUP_PREFIX}YYYYMMDDTHHMMSSZ), so nothing was deleted. "
                "Check --dest, and run a backup first."
            )
        # The plan took a while (verification); make sure the backup that must survive still does.
        if plan.clean is None or _status(plan.clean) != "clean":
            raise BackupError(f"{plan.clean.name if plan.clean else 'The clean backup'} no longer verifies cleanly, so nothing was deleted.")
        for path in [*plan.delete, *plan.stale_partials]:
            if path == plan.clean or path in plan.keep or path.is_symlink() or path.parent != destination:  # a last guard
                raise BackupError(f"Refusing to delete {path}.")
            doomed = path if _DELETING_NAME.fullmatch(path.name) else path.with_name(f".{path.name}.deleting-{uuid.uuid4().hex}")
            if doomed != path:
                os.rename(path, doomed)  # atomic: from here on it is no longer a backup (or unfinished run) folder
            shutil.rmtree(doomed)
    return replace(plan, applied=True)


def _plan_prune(destination: Path, keep_daily: int, keep_monthly: int, now: datetime | None) -> PrunePlan:
    backups = sorted(
        ((datetime.strptime(match["stamp"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), entry)
         for entry in destination.iterdir()
         if not entry.is_symlink() and entry.is_dir() and (match := _BACKUP_NAME.fullmatch(entry.name))),
        reverse=True,
    )
    keep: dict[Path, list[str]] = {}
    damaged: list[Path] = []
    incomplete: list[Path] = []
    clean = None
    for _, path in backups:  # newest first, until the newest clean one
        status = _status(path)
        if status == "clean":
            clean = path
            break
        if status == "damaged":
            damaged.append(path)
            keep.setdefault(path, []).append("does not verify; newer than the newest clean backup, kept for inspection")
        else:
            incomplete.append(path)
    if backups and clean is None:
        raise BackupError(
            f"No backup in {destination} verifies cleanly, so nothing was deleted. If the backups are incomplete "
            "(a dataset's stored file is missing or changed), the next backup is clean once that is fixed. "
            "Repair the dataset as described in deploy/README.md, \"Repairing a dataset whose stored file is missing\"."
        )
    if clean is not None:
        keep.setdefault(clean, []).append("newest backup that verifies cleanly")

    for label, key, count in (("daily", "%Y-%m-%d", keep_daily), ("monthly", "%Y-%m", keep_monthly)):
        periods: dict[str, Path] = {}
        for created, path in backups:  # newest first, so the first backup seen in a period is its newest
            period = created.strftime(key)
            if path not in damaged and period not in periods and len(periods) < count:  # damaged ones are kept anyway
                periods[period] = path
        for period, path in periods.items():
            keep.setdefault(path, []).append(f"{label} ({period})" + (", incomplete" if path in incomplete else ""))

    cutoff = (now or datetime.now(UTC)) - STALE_PARTIAL_AGE
    leftovers = [
        entry for entry in sorted(destination.iterdir())
        if not entry.is_symlink() and entry.is_dir()
        and (_DELETING_NAME.fullmatch(entry.name)  # a deletion that was interrupted: always safe to finish
             or (_PARTIAL_NAME.fullmatch(entry.name) and datetime.fromtimestamp(entry.stat().st_mtime, UTC) < cutoff))
    ]
    return PrunePlan(
        keep={path: keep[path] for _, path in backups if path in keep},
        delete=[path for _, path in reversed(backups) if path not in keep],
        stale_partials=leftovers,
        clean=clean,
        damaged=damaged,
        incomplete=incomplete,
        backup_bytes=sum(_folder_size(path) for _, path in backups),
        free_bytes=shutil.disk_usage(destination).free,
    )


def _status(path: Path) -> str:
    """'clean' (valid and complete), 'incomplete' (valid, some stored files missing), or 'damaged' (not valid)."""
    try:
        return "incomplete" if verify_backup(path).problems else "clean"
    except (BackupError, OSError, sqlite3.Error):
        return "damaged"


@contextmanager
def _prune_lock(destination: Path) -> Iterator[None]:
    """Allow one `prune --apply` at a time per backup folder, so two never act on each other's plans.

    An OS lock on PRUNE_LOCK in the folder: it is released when the process ends, even if it is killed, so it never
    goes stale. The file itself stays (it is reused). Backups and restores do not take it: a prune only deletes
    folders that existed when it planned, and a restore from a folder being deleted fails without restoring.
    """
    descriptor = os.open(destination / PRUNE_LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as error:
            raise BackupError(f"Another prune is already running on {destination}; nothing was deleted. Try again later.") from error
        yield
    finally:
        if locked and os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)  # also releases a POSIX lock


def _folder_size(path: Path) -> int:
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file() and not entry.is_symlink())


# ---------- Helpers ----------


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)


def _files_in(directory: Path) -> list[str]:
    """Regular files under `directory`, as relative paths. Links and special files are refused, not followed."""
    found = []
    for root, folders, files in os.walk(directory):
        for name in [*folders, *files]:
            entry = Path(root) / name
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise BackupError(f"{entry.relative_to(directory).as_posix()} is a symbolic link; backups never follow links.")
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise BackupError(f"{entry.relative_to(directory).as_posix()} is not a regular file.")
        found += [(Path(root) / name).relative_to(directory).as_posix() for name in files]
    return sorted(found)


@contextmanager
def _open_regular(path: Path) -> Iterator[BinaryIO]:
    """Open an existing regular file for reading without following a symbolic link (where the OS can refuse one)."""
    if path.is_symlink():
        raise BackupError(f"{path.name} is a symbolic link; backups never follow links.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BackupError(f"{path.name} cannot be opened safely: {error.strerror}.") from error
    with os.fdopen(descriptor, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise BackupError(f"{path.name} is not a regular file.")
        yield file


def _read_small_file(path: Path) -> bytes:
    with _open_regular(path) as file:
        return file.read()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _open_regular(path) as file:
        for chunk in iter(lambda: file.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _describe(problems: list[dict[str, Any]]) -> list[str]:
    return [
        f"Dataset {entry['dataset_id']}: its stored file {entry['file']} {_PROBLEM_REASONS.get(entry['reason'], entry['reason'])}, "
        "so it is not in this backup."
        for entry in problems
    ]


def _mb(size: int) -> str:
    return f"{size / 1_000_000:,.1f} MB"


# ---------- Command line ----------


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 done and complete; 1 failed; 2 done, but some datasets' files are not in the backup."""
    parser = argparse.ArgumentParser(
        prog="python -m app.storage.backup",
        description="Back up, check, restore, and prune backups of the InsightFlow dataset library.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Make a new backup folder inside --dest.")
    create.add_argument("--dest", type=Path, required=True, help="Folder that holds the backups (outside DATA_DIR).")
    create.add_argument("--data-dir", type=Path, help="Library to back up. Default: DATA_DIR from the settings.")
    verify = commands.add_parser("verify", help="Check a backup folder's checksums, manifest, and database.")
    verify.add_argument("backup", type=Path)
    restore = commands.add_parser("restore", help="Check a backup, then copy it into a new or empty folder.")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target", type=Path, required=True, help="New or empty folder to restore into.")
    prune = commands.add_parser("prune", help="Show (or with --apply, delete) backups outside the retention policy.")
    prune.add_argument("--dest", type=Path, required=True, help="Folder that holds the backups.")
    prune.add_argument("--keep-daily", type=int, default=DEFAULT_KEEP_DAILY, help=f"Days with backups to keep (default {DEFAULT_KEEP_DAILY}).")
    prune.add_argument("--keep-monthly", type=int, default=DEFAULT_KEEP_MONTHLY, help=f"Months to keep one backup of (default {DEFAULT_KEEP_MONTHLY}).")
    prune.add_argument("--apply", action="store_true", help="Delete. Without it, only the plan is printed.")
    args = parser.parse_args(argv)

    failure = {"create": "Backup failed", "verify": "Backup check failed", "restore": "Restore failed", "prune": "Prune failed"}[args.command]
    with _stop_cleanly_on_sigterm():
        try:
            if args.command == "prune":
                return _print_prune(prune_backups(args.dest, keep_daily=args.keep_daily, keep_monthly=args.keep_monthly, apply=args.apply))
            if args.command == "create":
                result = create_backup(args.data_dir or _configured_data_dir(), args.dest)
                print(f"Backup created: {result.path}")
            elif args.command == "verify":
                result = verify_backup(args.backup)
                print(f"Backup checked: {result.path} (every file matches its checksum)")
            else:
                result = restore_backup(args.backup, args.target)
                print(f"Restored into: {result.path}")
        except (BackupError, OSError, sqlite3.Error) as error:
            print(f"{failure}: {error}", file=sys.stderr)
            return 1

    print(f"Schema version {result.schema_version}, {result.datasets} datasets, {result.files} stored files.")
    if not result.problems:
        return 0
    for problem in result.problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    print(f"INCOMPLETE: {len(result.problems)} dataset(s) have no stored file in this backup (exit code 2).", file=sys.stderr)
    return 2


def _print_prune(plan: PrunePlan) -> int:
    if not plan.keep and not plan.delete:
        print(f"No backups found (folders named {BACKUP_PREFIX}YYYYMMDDTHHMMSSZ): nothing to prune.")
    for path, reasons in plan.keep.items():
        print(f"KEEP    {path.name}  ({'; '.join(reasons)})")
    for path in plan.delete:
        print(f"{'DELETED' if plan.applied else 'DELETE '} {path.name}")
    for path in plan.stale_partials:
        reason = "interrupted deletion" if _DELETING_NAME.fullmatch(path.name) else "unfinished folder of a stopped run"
        print(f"{'REMOVED' if plan.applied else 'REMOVE '} {path.name}  ({reason})")
    for path in plan.damaged:
        print(f"WARNING: {path.name} does not verify. Check it with verify.", file=sys.stderr)
    if plan.incomplete:
        print(
            f"NOTE: {len(plan.incomplete)} backup(s) newer than {plan.clean.name if plan.clean else 'the last clean one'} are "
            "incomplete: a dataset's stored file is missing or changed. Repair it (deploy/README.md, \"Repairing a "
            "dataset whose stored file is missing\") so backups are complete again.",
            file=sys.stderr,
        )
    print(f"Backups use {_mb(plan.backup_bytes)}; {_mb(plan.free_bytes)} free on that disk.")
    if not plan.applied and (plan.delete or plan.stale_partials):
        print("Preview only: nothing was deleted. Run again with --apply to delete the folders marked above.")
    return 0


@contextmanager
def _stop_cleanly_on_sigterm() -> Iterator[None]:
    """Turn SIGTERM (systemd stopping the job, for example after its timeout) into an exception, so an unfinished
    backup or restore folder is removed on the way out. A run killed outright (SIGKILL) leaves its unfinished
    folder behind; prune reports and removes those, and no folder ever gets a final name before it is complete."""
    def stop(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    try:
        previous = signal.signal(signal.SIGTERM, stop)
    except ValueError:  # not the main thread: leave signal handling alone
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _configured_data_dir() -> Path:
    from app.config import get_settings  # imported here so the module has no import-time settings

    return get_settings().data_dir


if __name__ == "__main__":
    sys.exit(main())
