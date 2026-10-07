"""Lifecycle against real repos and real pytest runs (SPEC §11, §12A.5, §19.8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seamspec.core import adr, journal, lifecycle, requests, verifier
from seamspec.core.config import load_config
from seamspec.core.models import DeadEnd, Invariant, InvStatus
from seamspec.core.schemas import validation_errors
from seamspec.core.store import Store

PASS = "from src.queue import backoff_delay\n\n\ndef test_cap():\n    assert backoff_delay(100) <= 30\n"
FAIL = "def test_fails():\n    assert 1 == 2\n"


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def shown(root: Path) -> dict[str, str]:
    """Fingerprints of the runner config as a reviewer would be shown it right now."""
    return verifier.current_fingerprints(root, load_config(root))


def propose(root: Path, code: str = PASS, **kw) -> dict:
    fields = dict(
        title="Retry delay is capped",
        assertion="Retry delay never exceeds 30 seconds.",
        scope_paths=["src/queue*"],
        runner="pytest",
        harness_code=code,
        origin_text="Add backoff, never more than 30s.",
    )
    fields.update(kw)
    return lifecycle.propose_invariant(Store(root), load_config(root), **fields)


# --- propose -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {"GIT_AUTHOR_NAME": "Maya Rao", "GIT_AUTHOR_EMAIL": "maya@example.com"},
        # no user.name anywhere: git falls back to the OS full name (if any); so must SeamSpec (dogfooding #5)
        {"GIT_AUTHOR_EMAIL": "maya@example.com"},
    ],
)
def test_approver_is_the_identity_git_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    import getpass
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    git_says = subprocess.run(["git", "var", "GIT_AUTHOR_IDENT"], cwd=tmp_path, capture_output=True, text=True)
    expected = git_says.stdout.strip().rsplit(" ", 2)[0] if git_says.returncode == 0 else getpass.getuser()
    if expected.startswith("<"):  # git found no name at all
        expected = getpass.getuser()
    assert lifecycle.approver_identity(Store(tmp_path)) == expected
    if "GIT_AUTHOR_NAME" in env:
        assert expected == "Maya Rao <maya@example.com>"


def test_propose_writes_outside_test_trees_and_runs_nothing(py_repo: Path) -> None:
    marker = py_repo / "ran.txt"
    out = propose(py_repo, code=f"open({str(marker)!r}, 'w').write('x')\n" + PASS)
    inv_id = out["id"]
    assert out["status"] == "PROPOSED" and out["verify"]["run"] == f"seamspec verify --proposed {inv_id}"
    assert out["harness_path"] == f".seamspec/proposed/{inv_id}/test_{inv_id}.py"
    assert (py_repo / out["harness_path"]).is_file()
    assert not (py_repo / f".seamspec/tests/test_{inv_id}.py").exists()
    assert not marker.exists(), "proposing must never execute the harness"
    data = json.loads((py_repo / f".seamspec/invariants/{inv_id}.json").read_text())
    assert validation_errors("invariant", data) == []


def test_propose_rejects_unknown_runner_and_empty_harness(py_repo: Path) -> None:
    with pytest.raises(lifecycle.LifecycleError, match="unknown runner 'jest'"):
        propose(py_repo, runner="jest")
    with pytest.raises(lifecycle.LifecycleError, match="empty"):
        propose(py_repo, code="   ")


def test_queue_full_for_agents_not_humans(py_repo: Path) -> None:
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("max_pending = 10", "max_pending = 2"))
    propose(py_repo)
    propose(py_repo)
    full = propose(py_repo)
    assert full == {"error": "queue_full", "pending": 2,
                    "message": "Review queue is full. Ask the user to run `seamspec review`."}  # fmt: skip
    assert "id" in propose(py_repo, by_human=True)


def test_replace_updates_in_place_and_is_exempt_from_cap(py_repo: Path) -> None:
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("max_pending = 10", "max_pending = 1"))
    first = propose(py_repo, code=FAIL)
    again = propose(py_repo, code=PASS, replace_id=first["id"], assertion="Retry delay is at most 30 seconds.")
    assert again["id"] == first["id"]
    assert (py_repo / again["harness_path"]).read_text() == PASS
    assert Store(py_repo).get(first["id"]).assertion == "Retry delay is at most 30 seconds."


def test_replace_only_proposed(py_repo: Path, human: None) -> None:
    inv_id = propose(py_repo)["id"]
    lifecycle.approve(Store(py_repo), load_config(py_repo), inv_id)
    with pytest.raises(lifecycle.LifecycleError, match="not a PROPOSED"):
        propose(py_repo, replace_id=inv_id)


def test_origin_text_is_redacted(py_repo: Path) -> None:
    out = propose(py_repo, origin_text="use key AKIAABCDEFGHIJKLMNOP and password=hunter2 please")
    text = Store(py_repo).get(out["id"]).origin.text
    assert "AKIA" not in text and "hunter2" not in text and text.count("[REDACTED]") == 2


def test_adr_draft_is_created_and_linked(py_repo: Path) -> None:
    out = propose(
        py_repo, adr_draft={"context": "Retry storms.", "decision": "Cap at 30s.", "consequences": ["Bounded"]}
    )
    record = adr.get(Store(py_repo), out["adr_id"])
    assert record.status == "PROPOSED" and record.invariants == [out["id"]]
    assert f"`{out['id']}` — Retry delay never exceeds 30 seconds." in record.body


# --- approve -------------------------------------------------------------------------------------


def test_approve_needs_a_terminal(py_repo: Path) -> None:
    inv_id = propose(py_repo)["id"]
    with pytest.raises(lifecycle.ApprovalError, match="interactive terminal"):
        lifecycle.approve(Store(py_repo), load_config(py_repo), inv_id)


def test_approve_locks_moves_hashes_and_journals(git_repo: Path, human: None) -> None:
    out = propose(git_repo, adr_draft={"context": "c", "decision": "d", "consequences": []})
    store = Store(git_repo)
    result = lifecycle.approve(store, load_config(git_repo), out["id"])
    inv = store.get(out["id"])
    assert isinstance(inv, Invariant) and inv.status == InvStatus.LOCKED
    assert inv.verification.harness_path == f".seamspec/tests/test_{out['id']}.py"
    assert not (git_repo / out["harness_path"]).exists()
    assert not (git_repo / ".seamspec/proposed" / out["id"]).exists()
    assert inv.approved_by == "Maya Rao <maya@example.com>"
    assert verifier.check_integrity(git_repo, inv) is None
    assert result.report.passed
    assert validation_errors("invariant", json.loads(store.path_for(inv.id).read_text())) == []
    assert [(e["id"], e["from"], e["to"]) for e in journal.entries(store)] == [(inv.id, "PROPOSED", "LOCKED")]
    assert adr.get(store, out["adr_id"]).status == "ACCEPTED"
    assert verifier.run(git_repo, load_config(git_repo), [inv]).passed


def test_failing_test_is_not_approved_and_nothing_changes(py_repo: Path, human: None) -> None:
    out = propose(py_repo, code=FAIL)
    prints_before = (py_repo / ".seamspec/fingerprints.json").read_text()
    ini = py_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "# reviewed tweak\n")
    store = Store(py_repo)
    with pytest.raises(lifecycle.ApprovalError, match="not passing"):
        lifecycle.approve(store, load_config(py_repo), out["id"], confirm_config=shown(py_repo))
    assert store.get(out["id"]).status == InvStatus.PROPOSED
    assert (py_repo / out["harness_path"]).is_file()
    assert not (py_repo / f".seamspec/tests/test_{out['id']}.py").exists()
    assert (py_repo / ".seamspec/fingerprints.json").read_text() == prints_before
    assert journal.entries(store) == []


def test_changed_runner_config_needs_explicit_confirmation(py_repo: Path, human: None) -> None:
    ini = py_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "# reviewed tweak\n")
    assert verifier.check_fingerprints(py_repo, load_config(py_repo))
    out = propose(py_repo)
    with pytest.raises(lifecycle.ApprovalError, match="runner config changed"):
        lifecycle.approve(Store(py_repo), load_config(py_repo), out["id"])
    assert Store(py_repo).get(out["id"]).status == InvStatus.PROPOSED
    stale = shown(py_repo)
    ini.write_text(ini.read_text() + "# changed again after being shown\n")
    with pytest.raises(lifecycle.ApprovalError, match="changed again after it was shown"):
        lifecycle.approve(Store(py_repo), load_config(py_repo), out["id"], confirm_config=stale)
    lifecycle.approve(Store(py_repo), load_config(py_repo), out["id"], confirm_config=shown(py_repo))
    assert verifier.check_fingerprints(py_repo, load_config(py_repo)) == []


def test_approve_wrong_status(py_repo: Path, human: None) -> None:
    out = propose(py_repo)
    lifecycle.approve(Store(py_repo), load_config(py_repo), out["id"])
    with pytest.raises(lifecycle.ApprovalError, match="LOCKED, not PROPOSED"):
        lifecycle.approve(Store(py_repo), load_config(py_repo), out["id"])


# --- reject, supersede, dead ends ------------------------------------------------------------------


def test_reject_retires_harness_and_can_record_dead_end(py_repo: Path, human: None) -> None:
    out = propose(py_repo)
    store = Store(py_repo)
    res = lifecycle.reject(store, load_config(py_repo), out["id"], "Wrong approach: cap belongs in config", True)
    inv = store.get(out["id"])
    assert inv.status == InvStatus.REJECTED and inv.status_reason.startswith("Wrong approach")
    assert inv.verification.harness_path == f".seamspec/retired/{out['id']}/test_{out['id']}.py"
    assert (py_repo / inv.verification.harness_path).is_file()
    de = store.get(res["dead_end"])
    assert isinstance(de, DeadEnd) and de.related_invariant == out["id"] and de.approach == inv.assertion


def test_supersede_via_request(git_repo: Path, human: None) -> None:
    store, cfg = Store(git_repo), load_config(git_repo)
    old = propose(git_repo)["id"]
    lifecycle.approve(store, cfg, old)
    new = propose(git_repo, assertion="Retry delay never exceeds 60 seconds.")["id"]

    lifecycle.request_supersede(store, old, "Batch jobs need 60s", new)
    assert requests.pending_supersede_ids(store) == {old}
    out = lifecycle.supersede(store, cfg, old)
    inv = store.get(old)
    assert out == {"id": old, "status": "SUPERSEDED", "superseded_by": new}
    assert inv.status_reason == "Batch jobs need 60s"
    assert inv.verification.harness_path.startswith(".seamspec/retired/")
    assert not (git_repo / f".seamspec/tests/test_{old}.py").exists()
    assert requests.pending_supersede_ids(store) == set()
    assert journal.unjournaled_changes(store) == []


def test_supersede_rules(py_repo: Path, human: None) -> None:
    store, cfg = Store(py_repo), load_config(py_repo)
    proposed = propose(py_repo)["id"]
    with pytest.raises(lifecycle.LifecycleError, match="not LOCKED"):
        lifecycle.request_supersede(store, proposed, "x")
    lifecycle.approve(store, cfg, proposed)
    with pytest.raises(lifecycle.LifecycleError, match="reason"):
        lifecycle.supersede(store, cfg, proposed)
    with pytest.raises(lifecycle.LifecycleError, match="replace itself"):
        lifecycle.request_supersede(store, proposed, "x", proposed)
    assert lifecycle.supersede(store, cfg, proposed, reason="Feature removed")["superseded_by"] is None


def test_dead_end_log_and_retire(py_repo: Path, human: None) -> None:
    store, cfg = Store(py_repo), load_config(py_repo)
    out = lifecycle.log_dead_end(
        store, cfg, scope_paths=["src/**"], approach="shared global retry counter", failure_symptom="x" * 5000
    )
    de = store.get(out["id"])
    assert de.status == "ACTIVE" and len(de.failure_symptom) == 1000 and de.source == "agent"
    lifecycle.retire_dead_end(store, out["id"], "fixed upstream")
    assert store.get(out["id"]).status == "RETIRED"
    with pytest.raises(lifecycle.LifecycleError, match="already RETIRED"):
        lifecycle.retire_dead_end(store, out["id"], "again")


def test_harness_in_place_copies_and_cleans_up(py_repo: Path) -> None:
    out = propose(py_repo)
    store, cfg = Store(py_repo), load_config(py_repo)
    inv = store.get(out["id"])
    final = py_repo / f".seamspec/tests/test_{out['id']}.py"
    with lifecycle.harness_in_place(store, cfg, inv) as staged:
        assert final.is_file() and staged.verification.harness_path == f".seamspec/tests/test_{out['id']}.py"
        assert verifier.run(py_repo, cfg, [staged]).passed
    assert not final.exists() and (py_repo / out["harness_path"]).is_file()
