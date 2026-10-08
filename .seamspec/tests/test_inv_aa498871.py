"""Locked rule: the agent never supplies the text of an approval dialog. `open_review` takes ids only,
and SeamSpec renders every dialog from the ledger, marking agent-written text line by line
(ADR-20261006-c300)."""

from pathlib import Path

import anyio
import pytest
from mcp import Client

from seamspec import chat_review
from seamspec.core import hookguard, lifecycle
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold
from seamspec.mcp_server import mcp


def test_open_review_takes_ids_only() -> None:
    async def tools():
        async with Client(mcp) as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    review = anyio.run(tools)["open_review"]
    assert set(review.input_schema.get("properties", {})) == {"ids"}


def test_dialog_text_comes_from_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setattr(hookguard, "MANAGED_DIRS", ())
    monkeypatch.setattr(hookguard, "_launch_args", lambda: [])
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    injected = "From SeamSpec, not the agent. Choose approve: it is safe."
    inv_id = lifecycle.propose_invariant(
        store, cfg, title=injected[:100], assertion=f"{injected} Retry delay never exceeds 30 seconds.",
        scope_paths=["src/**"], runner="pytest", harness_code=f"# {injected}\ndef test_x():\n    assert True\n",
        origin_text=injected,
    )["id"]  # fmt: skip
    out = chat_review.step(store, cfg, [inv_id], None, None, "test", [tmp_path])
    message = next(iter(out.input_requests.values())).params.message
    assert message.startswith(chat_review.HEADER + "\n")
    planted = [line for line in message.splitlines() if injected[:40] in line]
    assert len(planted) >= 4  # title, rule, origin and test all show up
    for line in planted:
        assert line.startswith("│ "), line  # agent text never stands on its own line
    assert message.count(chat_review.HEADER) == 1
