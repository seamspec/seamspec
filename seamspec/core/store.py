"""Per-record ledger storage (SPEC §9.2, §19.4).

One JSON file per record, so two branches adding records never conflict. Writes are atomic
(temp file + fsync + rename) and serialized with a file lock in `.seamspec/.local/`.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import tempfile
from pathlib import Path

from filelock import FileLock
from pydantic import BaseModel, ValidationError

from .models import DeadEnd, Invariant

Record = Invariant | DeadEnd

KINDS: dict[str, tuple[str, type[BaseModel]]] = {
    "inv": ("invariants", Invariant),
    "de": ("dead_ends", DeadEnd),
}
_ID_RE = re.compile(r"^(inv|de)_[a-f0-9]{8}$")


class RecordError(RuntimeError):
    """A record file exists but can't be read or doesn't match its model."""


class DuplicateRecord(RuntimeError):
    pass


def _current_umask() -> int:
    # os.umask can only be read by setting it; restore immediately.
    mask = os.umask(0)
    os.umask(mask)
    return mask


def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + fsync + os.replace so readers never see partial files.

    mkstemp creates owner-only (0600) files, so the final mode is set explicitly: an existing
    file keeps its mode, a new one gets the usual 0666 minus the umask (typically 0644)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o666 & ~_current_umask()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if hasattr(os, "fchmod"):  # POSIX; Windows has no Unix modes
                os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _prefix(record_id: str) -> str:
    # Validating the id also keeps callers from building paths outside the ledger.
    if not _ID_RE.match(record_id):
        raise KeyError(f"invalid record id {record_id!r}")
    return record_id.split("_", 1)[0]


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = root / ".seamspec"
        self.local = self.base / ".local"
        self.local.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.local / "store.lock"), timeout=10)

    def _folder(self, prefix: str) -> Path:
        return self.base / KINDS[prefix][0]

    def path_for(self, record_id: str) -> Path:
        return self._folder(_prefix(record_id)) / f"{record_id}.json"

    def new_id(self, prefix: str) -> str:
        folder = self._folder(prefix)
        while True:
            candidate = f"{prefix}_{secrets.token_hex(4)}"
            if not (folder / f"{candidate}.json").exists():
                return candidate

    def create(self, record: Record) -> Path:
        """Save a new record; refuses to overwrite an existing id."""
        path = self.path_for(record.id)
        with self._lock:
            if path.exists():
                raise DuplicateRecord(record.id)
            atomic_write(path, record.model_dump_json(indent=2) + "\n")
        return path

    def save(self, record: Record) -> Path:
        """Create or replace a record."""
        path = self.path_for(record.id)
        with self._lock:
            atomic_write(path, record.model_dump_json(indent=2) + "\n")
        return path

    def _load(self, path: Path, model: type[BaseModel]) -> Record:
        try:
            return model.model_validate_json(path.read_text(encoding="utf-8"))  # type: ignore[return-value]
        except (OSError, ValidationError) as exc:
            raise RecordError(f"{path.relative_to(self.root).as_posix()}: {exc}") from exc

    def load_all(self, prefix: str) -> list[Record]:
        """All records of a kind. Raises RecordError naming the first bad file."""
        folder, model = self._folder(prefix), KINDS[prefix][1]
        if not folder.is_dir():
            return []
        return [self._load(p, model) for p in sorted(folder.glob(f"{prefix}_*.json"))]

    def get(self, record_id: str) -> Record:
        path = self.path_for(record_id)
        if not path.is_file():
            raise KeyError(record_id)
        return self._load(path, KINDS[_prefix(record_id)][1])

    def revision(self) -> str:
        """Content hash of all records; changes whenever the ledger changes."""
        h = hashlib.sha256()
        for prefix in KINDS:
            folder = self._folder(prefix)
            if folder.is_dir():
                for p in sorted(folder.glob("*.json")):
                    h.update(p.name.encode())
                    h.update(p.read_bytes())
        return h.hexdigest()[:16]
