"""Rule: a locked rule is never retired while the replacement named for it is only proposed
(ADR-20261013-7c2e). Stopping halfway through a swap must never leave the behavior with no rule."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store
from seamspec.installers import scaffold


def swap(tmp_path: Path) -> tuple[Store, str, str]:
    """A locked rule, a proposed replacement, and the agent's request to swap them."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    fields = dict(assertion="This test always passes.", scope_paths=["src/**"], runner="pytest",
                  harness_code="def test_x():\n    assert True\n", origin_text="x")  # fmt: skip
    old = lifecycle.propose_invariant(store, cfg, title="Old rule", **fields)["id"]
    lifecycle.approve(store, cfg, old, via="chat")
    new = lifecycle.propose_invariant(store, cfg, title="New rule", **fields)["id"]
    lifecycle.request_supersede(store, old, "The requirement changed", new)
    return store, old, new


def test_supersede_refuses_until_the_replacement_is_locked(tmp_path: Path) -> None:
    store, old, new = swap(tmp_path)
    cfg = load_config(tmp_path)
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.supersede(store, cfg, old, via="chat")
    assert store.get(old).status == InvStatus.LOCKED
    assert (tmp_path / f".seamspec/tests/test_{old}.py").is_file()  # its test still runs

    lifecycle.approve(store, cfg, new, via="chat")
    lifecycle.supersede(store, cfg, old, via="chat")
    assert store.get(old).status == InvStatus.SUPERSEDED and store.get(old).superseded_by == new


@pytest.mark.parametrize("answers", ["n\ns\n", "n\nq\n", "n\nd\nn\n", ""])  # skip, quit, decline, input ends
def test_no_way_through_the_review_retires_the_old_rule_alone(tmp_path: Path, monkeypatch, answers: str) -> None:
    store, old, new = swap(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    CliRunner().invoke(app, ["review"], input=answers)
    assert store.get(old).status == InvStatus.LOCKED
    assert store.get(new).status == InvStatus.PROPOSED
