from __future__ import annotations

from seamspec.core.context import constraints_for
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .conftest import make_dead_end, make_invariant


def test_selects_by_scope_and_status(store: Store) -> None:
    store.create(make_invariant("inv_00000001", InvStatus.LOCKED, adr_id="ADR-20261003-4f8a"))
    store.create(make_invariant("inv_00000002", InvStatus.PROPOSED))
    store.create(make_invariant("inv_00000003", InvStatus.SUPERSEDED))
    store.create(make_invariant("inv_00000004", InvStatus.REJECTED))
    store.create(make_invariant("inv_00000005", InvStatus.LOCKED, paths=["src/auth/**"]))
    store.create(make_dead_end("de_00000001"))
    store.create(make_dead_end("de_00000002", status="RETIRED", retired_reason="fixed"))

    cs = constraints_for(store, [str(store.root / "src/queue/redis.py")])
    assert cs.files == ["src/queue/redis.py"]
    assert [i.id for i in cs.locked] == ["inv_00000001"]
    assert [i.id for i in cs.proposed] == ["inv_00000002"]
    assert [d.id for d in cs.dead_ends] == ["de_00000001"]
    assert not cs.empty


def test_render_reads_as_history(store: Store) -> None:
    store.create(make_invariant("inv_00000001", InvStatus.LOCKED, adr_id="ADR-20261003-4f8a"))
    store.create(make_dead_end())
    text = constraints_for(store, ["src/queue/redis.py"]).render()
    assert "- [LOCKED] inv_00000001: Exponential backoff" in text
    assert "(ADR-20261003-4f8a)" in text
    assert "Previously tried and failed:" in text
    assert "tried a global retry counter shared across workers; failed previously because" in text
    assert "(recorded 2026-10-03)" in text
    assert "Don't" not in text and "Avoid" not in text
    assert not text.startswith("SeamSpec:")  # callers add the header


def test_proposed_only_is_empty_for_gating(store: Store) -> None:
    store.create(make_invariant())
    cs = constraints_for(store, ["src/queue/redis.py"])
    assert cs.proposed and cs.empty


def test_files_outside_repo_are_ignored(store: Store) -> None:
    store.create(make_invariant(status=InvStatus.LOCKED, paths=["**"]))
    cs = constraints_for(store, [str(store.root.parent / "elsewhere.py")])
    assert cs.files == [] and cs.locked == []


def test_limit_reports_omitted(store: Store) -> None:
    for n in range(5):
        store.create(make_invariant(f"inv_{n:08x}", InvStatus.LOCKED))
    cs = constraints_for(store, ["src/queue/x.py"], limit=2)
    assert len(cs.locked) == 2 and cs.omitted == 3
    assert "... and 3 more" in cs.render()


def test_to_dict_is_json_ready(store: Store) -> None:
    store.create(make_invariant(status=InvStatus.LOCKED))
    data = constraints_for(store, ["src/queue/x.py"]).to_dict()
    assert data["locked"][0]["status"] == "LOCKED"
    assert data["locked"][0]["created_at"].endswith("Z")
