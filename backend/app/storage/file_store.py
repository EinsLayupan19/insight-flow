"""Stored copies of saved CSV files, on local disk.

Each file is named after the SHA-256 hash of its content (for example
"3f9c...e1.csv"). The name the user uploaded is only stored as a label in the
database and is never used as a path, so a crafted filename cannot write
outside this directory. Reading a file checks its hash, so an analysis never
runs on a file that changed on disk after it was saved.
"""

import hashlib
import os
import re
import uuid
from pathlib import Path

_SHA256 = re.compile(r"[0-9a-f]{64}")


class StoredFileError(Exception):
    """The stored copy of a dataset is missing or no longer matches its hash. The message is shown to users."""


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FileStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, sha256: str) -> Path:
        if not _SHA256.fullmatch(sha256):
            raise ValueError(f"Not a SHA-256 hex digest: {sha256!r}")
        return self.directory / f"{sha256}.csv"

    def save(self, content: bytes, sha256: str) -> str:
        """Store `content` and return the stored file's name. Saving the same content twice is harmless."""
        path = self.path_for(sha256)
        if path.is_file() and sha256_of(path.read_bytes()) == sha256:
            return path.name  # an intact copy is already there: nothing to write
        self.directory.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name, then rename: readers never see a half-written file.
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path.name

    def read(self, sha256: str) -> bytes:
        """Return the stored content, after checking it still matches its hash."""
        try:
            content = self.path_for(sha256).read_bytes()
        except FileNotFoundError as error:
            raise StoredFileError(
                "The stored copy of this dataset is missing from the server's disk. "
                "Delete the dataset and save the file again."
            ) from error
        if sha256_of(content) != sha256:
            raise StoredFileError(
                "The stored copy of this dataset changed on disk after it was saved, so it can no longer be trusted. "
                "Delete the dataset and save the file again."
            )
        return content

    def is_stored(self, sha256: str, size_bytes: int) -> bool:
        """Quick check (no hashing): the stored file exists and has the expected size."""
        path = self.path_for(sha256)
        return path.is_file() and path.stat().st_size == size_bytes

    def delete(self, sha256: str) -> None:
        self.path_for(sha256).unlink(missing_ok=True)
