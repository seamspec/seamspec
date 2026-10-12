"""Rule: the generated spec depends on the ledger alone. The same records give the same bytes,
whatever else is on the machine, so a committed copy can be checked in CI (ADR-20261013-2f6b)."""

from pathlib import Path

from seamspec.core import lifecycle, specdoc
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold


def test_nothing_outside_the_ledger_changes_the_spec(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    for scope in (["runs"], ["src/billing"], ["docs/**"]):
        inv_id = lifecycle.propose_invariant(
            store, cfg, title=f"Rule for {scope[0]}", assertion="This behavior holds.", scope_paths=scope,
            runner="pytest", harness_code="def test_x():\n    assert True\n", origin_text="x",
        )["id"]  # fmt: skip
        lifecycle.approve(store, cfg, inv_id, via="chat")
    lifecycle.log_dead_end(store, cfg, scope_paths=["runs"], approach="Caching every response on disk",
                           failure_symptom="The disk filled up within a day.")  # fmt: skip
    before = specdoc.render(store, generated_line=True)

    # What differs between two machines: folders that exist only here, the local journal, a later proposal.
    for folder in ("runs", "src/billing", "docs"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".seamspec/.local/journal.jsonl").unlink()
    lifecycle.propose_invariant(store, cfg, title="Proposed later", assertion="Not approved by anyone yet.",
                                scope_paths=["src/**"], runner="pytest", harness_code="def test_x():\n    assert True\n",
                                origin_text="x")  # fmt: skip

    assert specdoc.render(Store(tmp_path), generated_line=True) == before
    assert "maya@example.com" not in before and str(tmp_path) not in before and tmp_path.name not in before
