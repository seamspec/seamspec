"""Rule: the generated spec lists only what a human approved. A proposed or rejected rule never
appears in it, by id, title or text (ADR-20261013-2f6b)."""

from pathlib import Path

from seamspec.core import lifecycle, specdoc
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold


def test_only_approved_rules_are_in_the_spec(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)

    def propose(title: str, assertion: str) -> str:
        return lifecycle.propose_invariant(
            store, cfg, title=title, assertion=assertion, scope_paths=["src/**"], runner="pytest",
            harness_code="def test_x():\n    assert True\n", origin_text="x",
        )["id"]  # fmt: skip

    locked = propose("Approved rule", "The approved behavior holds.")
    lifecycle.approve(store, cfg, locked, via="chat")
    waiting = propose("Waiting rule", "Nobody has decided about this one.")
    refused = propose("Refused rule", "A human said no to this one.")
    lifecycle.reject(store, cfg, refused, "not wanted", via="chat")

    text = specdoc.render(store)

    assert locked in text and "Approved rule" in text and "The approved behavior holds." in text
    for absent in (waiting, "Waiting rule", "Nobody has decided", refused, "Refused rule", "A human said no"):
        assert absent not in text
    assert "1 rule in force" in text
