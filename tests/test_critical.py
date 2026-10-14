"""Critical rules (ADR-20261013-c1a9): a human marks a few rules that the agent must always see in
full. The mark changes how a rule is shown, never whether it is enforced."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.adapters import claude
from seamspec.cli import app
from seamspec.core import doctor, journal, lifecycle, specdoc
from seamspec.core.config import load_config
from seamspec.core.context import constraints_for
from seamspec.core.models import Invariant
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import propose

runner = CliRunner()


@pytest.fixture
def human(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    monkeypatch.chdir(git_repo)  # the CLI finds the project from the current folder


def locked(root: Path, **kw) -> str:
    inv_id = propose(root, **kw)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    return inv_id


def test_the_agent_can_suggest_it_and_approval_keeps_it(git_repo: Path, human: None) -> None:
    store, cfg = Store(git_repo), load_config(git_repo)
    inv_id = propose(git_repo, critical=True)["id"]
    assert store.get(inv_id).critical is True
    out = runner.invoke(app, ["review"], input="n\ns\n")
    assert "Critical: yes, always shown to the agent in full (as proposed by the agent;" in out.output
    lifecycle.approve(store, cfg, inv_id)
    assert store.get(inv_id).critical is True and propose(git_repo)["id"]  # the default stays False
    assert Invariant.model_validate({**store.get(inv_id).model_dump(), "critical": False}).critical is False


def test_only_a_human_sets_or_clears_it_and_it_is_noted(git_repo: Path, human: None, monkeypatch) -> None:
    store = Store(git_repo)
    inv_id = locked(git_repo)
    out = runner.invoke(app, ["critical", inv_id])
    assert out.exit_code == 0 and store.get(inv_id).critical is True
    events = [line for line in (store.local / journal.JOURNAL).read_text().splitlines() if "critical" in line]
    assert json.loads(events[-1])["event"] == "critical_marked" and json.loads(events[-1])["item"] == inv_id
    assert runner.invoke(app, ["critical", inv_id, "--off"]).exit_code == 0 and store.get(inv_id).critical is False
    monkeypatch.delenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE")  # an agent's shell: no terminal
    refused = runner.invoke(app, ["critical", inv_id])
    assert refused.exit_code == 1 and store.get(inv_id).critical is False
    lifecycle.supersede(store, load_config(git_repo), inv_id, reason="gone", via="chat")
    with pytest.raises(lifecycle.LifecycleError, match="only a proposed or locked rule"):
        lifecycle.set_critical(store, inv_id, True, via="chat")


def test_session_summary_keeps_critical_rules_in_full_at_every_size(git_repo: Path, human: None) -> None:
    store = Store(git_repo)
    key = locked(git_repo, title="Payments are never charged twice", assertion="A payment id is charged at most once, "
                 "even when the provider times out and the request is retried by the client.")  # fmt: skip
    lifecycle.set_critical(store, key, True)
    for n in range(4):
        locked(git_repo, title=f"Ordinary rule {n}", assertion=f"Ordinary behavior number {n} holds for everyone.")
    roomy = claude.session_summary(store)
    assert roomy.startswith(claude.CRITICAL_HEADING) and roomy.count("Payments are never charged twice") == 1
    for size in (900, 600, 400):  # the other rules shrink to titles, then to counts; the critical one stays whole
        tight = claude.session_summary(store, max_chars=size)
        assert "A payment id is charged at most once, even when the provider times out" in tight, size
    assert "4 other rules in force" in claude.session_summary(store, max_chars=400)


def test_marked_where_rules_are_shown_and_never_changes_enforcement(git_repo: Path, human: None) -> None:
    store, cfg = Store(git_repo), load_config(git_repo)
    inv_id = locked(git_repo)
    lifecycle.set_critical(store, inv_id, True)
    assert f"[LOCKED, CRITICAL] {inv_id}" in constraints_for(store, [str(git_repo / "src/queue.py")]).render()
    assert "- **Critical:** always shown to the agent in full" in specdoc.render(store)
    status = json.loads(runner.invoke(app, ["status", "--json"]).output)
    assert status["critical"] == 1
    from seamspec.core import verifier

    before = verifier.run(git_repo, cfg, [store.get(inv_id)]).passed
    lifecycle.set_critical(store, inv_id, False)
    assert verifier.run(git_repo, cfg, [store.get(inv_id)]).passed == before  # the same test, run the same way


def test_doctor_notes_a_removed_mark_in_ci_and_too_many_marks(git_repo: Path, human: None) -> None:
    store = Store(git_repo)
    inv_id = locked(git_repo)
    lifecycle.set_critical(store, inv_id, True)
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-qm", "mark it")
    lifecycle.set_critical(store, inv_id, False)
    ci = doctor.run(git_repo, ci=True, base_ref="HEAD")
    assert any(f.check == "critical" and inv_id in f.message and f.level == "warning" for f in ci.findings)
    assert not [f for f in ci.findings if f.level == "error" and f.check == "forward-only"]  # allowed, only shown
    for n in range(doctor.CRITICAL_MANY + 1):
        lifecycle.set_critical(
            store, locked(git_repo, title=f"Rule {n}", assertion=f"Behavior {n} always holds."), True
        )
    assert any(f.check == "critical" and "meant for a few rules" in f.message for f in doctor.run(git_repo).findings)
