from __future__ import annotations

import json
import threading

import pytest

from seamspec.core.models import InvStatus
from seamspec.core.schemas import validation_errors
from seamspec.core.store import DuplicateRecord, RecordError, Store

from .conftest import make_dead_end, make_invariant


def test_create_get_load_all(store: Store) -> None:
    inv, de = make_invariant(), make_dead_end()
    assert store.create(inv) == store.root / ".seamspec/invariants/inv_1a2b3c4d.json"
    store.create(de)
    assert store.get(inv.id) == inv
    assert store.get(de.id) == de
    assert store.load_all("inv") == [inv]
    assert store.load_all("de") == [de]


def test_written_files_validate_against_schemas(store: Store) -> None:
    store.create(make_invariant(status=InvStatus.LOCKED))
    store.create(make_dead_end())
    inv_data = json.loads((store.base / "invariants/inv_1a2b3c4d.json").read_text())
    de_data = json.loads((store.base / "dead_ends/de_9f8e7d6c.json").read_text())
    assert validation_errors("invariant", inv_data) == []
    assert validation_errors("dead_end", de_data) == []


def test_create_refuses_overwrite_save_replaces(store: Store) -> None:
    store.create(make_invariant())
    with pytest.raises(DuplicateRecord):
        store.create(make_invariant())
    store.save(make_invariant(title="A new title"))
    assert store.get("inv_1a2b3c4d").title == "A new title"


def test_no_temp_files_left(store: Store) -> None:
    store.create(make_invariant())
    store.save(make_invariant(title="Again"))
    leftovers = [p.name for p in (store.base / "invariants").iterdir() if p.name.startswith(".")]
    assert leftovers == []


@pytest.mark.parametrize("bad", ["inv_../../x", "../config", "inv_1A2B3C4D", "adr_12345678", "inv_123"])
def test_invalid_ids_rejected(store: Store, bad: str) -> None:
    with pytest.raises(KeyError):
        store.get(bad)


def test_missing_record(store: Store) -> None:
    with pytest.raises(KeyError):
        store.get("inv_00000000")


def test_bad_record_names_the_file(store: Store) -> None:
    (store.base / "invariants").mkdir(exist_ok=True)
    (store.base / "invariants/inv_deadbeef.json").write_text('{"id": "inv_deadbeef"}')
    with pytest.raises(RecordError, match="invariants/inv_deadbeef.json"):
        store.load_all("inv")


def test_new_id_format_and_uniqueness(store: Store) -> None:
    ids = {store.new_id("inv") for _ in range(50)}
    assert len(ids) == 50 and all(i.startswith("inv_") and len(i) == 12 for i in ids)


def test_revision_changes_with_ledger(store: Store) -> None:
    r0 = store.revision()
    store.create(make_invariant())
    r1 = store.revision()
    store.save(make_invariant(title="Changed title"))
    assert len({r0, r1, store.revision()}) == 3


def test_concurrent_creates(store: Store) -> None:
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            store.create(make_invariant(inv_id=f"inv_{n:08x}"))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.load_all("inv")) == 20


def test_new_files_follow_umask_and_existing_files_keep_their_mode(tmp_path, monkeypatch) -> None:
    """Finding #5: mkstemp's owner-only mode must not leak into files people commit."""
    import os
    import stat

    from seamspec.core.store import atomic_write

    old = os.umask(0o022)
    try:
        new = tmp_path / "CLAUDE.md"
        atomic_write(new, "x\n")
        assert stat.S_IMODE(new.stat().st_mode) == 0o644
        new.chmod(0o640)
        atomic_write(new, "y\n")
        assert stat.S_IMODE(new.stat().st_mode) == 0o640 and new.read_text() == "y\n"
    finally:
        os.umask(old)
