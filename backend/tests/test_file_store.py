"""Stored CSV files: content-addressed names, integrity checks, and safe deletion."""

from pathlib import Path

import pytest

from app.storage.file_store import FileStore, StoredFileError, sha256_of

CONTENT = b"store,revenue\nNorth,100\n"


def test_saved_file_is_named_by_its_hash_and_reads_back_exactly(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    digest = sha256_of(CONTENT)

    name = store.save(CONTENT, digest)

    assert name == f"{digest}.csv"
    assert store.read(digest) == CONTENT
    assert store.is_stored(digest, len(CONTENT))


def test_saving_the_same_content_twice_is_harmless(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    digest = sha256_of(CONTENT)

    store.save(CONTENT, digest)
    store.save(CONTENT, digest)

    assert [path.name for path in (tmp_path / "uploads").iterdir()] == [f"{digest}.csv"]


def test_reading_a_missing_file_explains_what_happened(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")

    with pytest.raises(StoredFileError, match="missing"):
        store.read(sha256_of(CONTENT))


def test_a_file_changed_on_disk_is_not_trusted(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    digest = sha256_of(CONTENT)
    store.save(CONTENT, digest)
    store.path_for(digest).write_bytes(b"store,revenue\nNorth,999\n")

    with pytest.raises(StoredFileError, match="changed on disk"):
        store.read(digest)


def test_a_damaged_copy_is_replaced_when_the_same_content_is_saved_again(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    digest = sha256_of(CONTENT)
    store.save(CONTENT, digest)
    store.path_for(digest).write_bytes(b"x" * len(CONTENT))  # same size, different bytes

    store.save(CONTENT, digest)

    assert store.read(digest) == CONTENT


def test_delete_is_idempotent(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    digest = sha256_of(CONTENT)
    store.save(CONTENT, digest)

    store.delete(digest)
    store.delete(digest)

    assert not store.is_stored(digest, len(CONTENT))


@pytest.mark.parametrize("name", ["../../etc/passwd", "sales.csv", "A" * 64, ""])
def test_only_hash_names_can_become_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        FileStore(tmp_path).path_for(name)
