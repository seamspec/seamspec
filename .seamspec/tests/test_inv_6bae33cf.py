"""Locked rule: approvals in chat are refused while a hook SeamSpec can see could answer or rewrite
its dialogs, checked before the dialog and again before acting on the answer (ADR-20261006-c300)."""

import json
from pathlib import Path

import pytest
from mcp_types import ElicitResult

from seamspec import chat_review
from seamspec.core import hookguard, lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import Invariant, InvStatus
from seamspec.core.store import Store
from seamspec.installers import scaffold


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Store, str]:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setattr(hookguard, "MANAGED_DIRS", ())
    monkeypatch.setattr(hookguard, "_launch_args", lambda: [])
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store = Store(tmp_path)
    inv_id = lifecycle.propose_invariant(
        store, load_config(tmp_path), title="Always true", assertion="This test always passes.",
        scope_paths=["src/**"], runner="pytest", harness_code="def test_x():\n    assert True\n", origin_text="x",
    )["id"]  # fmt: skip
    return store, inv_id


def add_hook(root: Path, event: str, matcher: str | None) -> None:
    group: dict = {"hooks": [{"type": "command", "command": "echo"}]}
    if matcher is not None:
        group["matcher"] = matcher
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {event: [group]}}))


def status(store: Store, inv_id: str) -> InvStatus:
    record = store.get(inv_id)
    assert isinstance(record, Invariant)
    return record.status


@pytest.mark.parametrize("event", ["Elicitation", "ElicitationResult"])
@pytest.mark.parametrize("matcher", [None, "*", "plugin:seamspec:seamspec", "plugin:.*"])
def test_refused_before_the_dialog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str,
                                   matcher: str | None) -> None:  # fmt: skip
    store, inv_id = setup(tmp_path, monkeypatch)
    add_hook(tmp_path, event, matcher)
    out = chat_review.step(store, load_config(tmp_path), [inv_id], None, None, "test", [tmp_path])
    assert isinstance(out, dict) and "won't take approvals in chat" in out["message"]
    assert status(store, inv_id) == InvStatus.PROPOSED


def test_refused_before_acting_on_the_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, inv_id = setup(tmp_path, monkeypatch)
    cfg = load_config(tmp_path)
    dialog = chat_review.step(store, cfg, [inv_id], None, None, "test", [tmp_path])
    key, request = next(iter(dialog.input_requests.items()))
    approve = next(c for c in request.params.requested_schema["properties"]["decision"]["enum"]
                   if c.startswith("approve-"))  # fmt: skip
    add_hook(tmp_path, "ElicitationResult", None)  # added while the dialog is open
    answer = ElicitResult(action="accept", content={"decision": approve})
    out = chat_review.step(store, cfg, [inv_id], dialog.request_state, {key: answer}, "test", [tmp_path])
    assert isinstance(out, dict) and "won't take approvals in chat" in out["message"]
    assert status(store, inv_id) == InvStatus.PROPOSED
