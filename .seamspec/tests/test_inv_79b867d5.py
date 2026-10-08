"""Locked rule: every human decision records where it was made: `decided_via` ("terminal" or "chat")
in the committed record, and `via` (plus the chat client) in the journal (ADR-20261006-c300)."""

from pathlib import Path

import pytest

from seamspec.core import journal, lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import DeadEnd, Invariant
from seamspec.core.store import Store
from seamspec.installers import scaffold


def setup(tmp_path: Path) -> tuple[Store, str, str]:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    fields = dict(assertion="This test always passes.", scope_paths=["src/**"], runner="pytest",
                  harness_code="def test_x():\n    assert True\n", origin_text="x")  # fmt: skip
    first = lifecycle.propose_invariant(store, cfg, title="First rule", **fields)["id"]
    second = lifecycle.propose_invariant(store, cfg, title="Second rule", **fields)["id"]
    return store, first, second


def test_chat_decisions_record_chat(tmp_path: Path) -> None:
    store, inv_id, _ = setup(tmp_path)
    cfg = load_config(tmp_path)
    lifecycle.reject(store, cfg, inv_id, "Too narrow", via="chat", client="claude-code 9.9")
    record = store.get(inv_id)
    assert isinstance(record, Invariant) and record.decided_via == "chat"
    entry = journal.entries(store)[-1]
    assert (entry["id"], entry["via"], entry["client"]) == (inv_id, "chat", "claude-code 9.9")

    de_id = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach="A global retry counter",
                                   failure_symptom="Starved other jobs")["id"]  # fmt: skip
    lifecycle.retire_dead_end(store, de_id, "Fixed upstream", via="chat", client="claude-code 9.9")
    dead = store.get(de_id)
    assert isinstance(dead, DeadEnd) and dead.decided_via == "chat"
    entry = journal.entries(store)[-1]
    assert (entry["id"], entry["from"], entry["to"], entry["via"]) == (de_id, "ACTIVE", "RETIRED", "chat")


def test_approve_and_supersede_record_where(tmp_path: Path) -> None:
    store, first, second = setup(tmp_path)
    cfg = load_config(tmp_path)
    lifecycle.approve(store, cfg, first, via="chat", client="claude-code 9.9")
    locked = store.get(first)
    assert isinstance(locked, Invariant) and locked.decided_via == "chat"
    entry = journal.entries(store)[-1]
    assert (entry["id"], entry["to"], entry["via"], entry["client"]) == (first, "LOCKED", "chat", "claude-code 9.9")
    lifecycle.request_supersede(store, first, "Requirement changed")
    lifecycle.supersede(store, cfg, first, via="chat", client="claude-code 9.9")
    retired = store.get(first)
    assert isinstance(retired, Invariant) and retired.decided_via == "chat"
    entry = journal.entries(store)[-1]
    assert (entry["id"], entry["to"], entry["via"]) == (first, "SUPERSEDED", "chat")


def test_terminal_decisions_record_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")  # stands in for the terminal
    store, first, second = setup(tmp_path)
    cfg = load_config(tmp_path)
    lifecycle.reject(store, cfg, second, "Wrong scope")
    lifecycle.approve(store, cfg, first)
    for inv_id in (first, second):
        record = store.get(inv_id)
        assert isinstance(record, Invariant) and record.decided_via == "terminal"
    assert [e["via"] for e in journal.entries(store)[-2:]] == ["terminal", "terminal"]
