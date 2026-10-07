"""Approval journal against real git history (SPEC §11.1) and ADR files (§10.3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from seamspec.core import adr, journal, lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .conftest import git, make_invariant
from .test_lifecycle import propose

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def locked_and_committed(root: Path) -> str:
    inv_id = propose(root)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "lock")
    (Store(root).local / journal.JOURNAL).unlink()  # a fresh clone has no journal
    return inv_id


def flip(store: Store, inv_id: str, **update) -> None:
    """Edit a record directly, as an agent with a shell could."""
    store.save(store.get(inv_id).model_copy(update=update))


def test_clean_repo_has_no_problems(git_repo: Path, human: None) -> None:
    locked_and_committed(git_repo)
    assert journal.unjournaled_changes(Store(git_repo)) == []


def test_silent_retirement_is_flagged(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    store = Store(git_repo)
    flip(store, inv_id, status=InvStatus.SUPERSEDED, status_reason="sneaky")
    assert journal.unjournaled_changes(store) == [
        f"{inv_id} was changed from LOCKED to SUPERSEDED outside the SeamSpec CLI. "
        "Revert it, or ask the user to run `seamspec review`."
    ]


def test_cli_retirement_is_not_flagged(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    store = Store(git_repo)
    lifecycle.supersede(store, load_config(git_repo), inv_id, reason="requirement changed")
    assert journal.unjournaled_changes(store) == []


def test_back_to_proposed_is_flagged(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    store = Store(git_repo)
    flip(store, inv_id, status=InvStatus.PROPOSED, approved_at=None, approved_by=None)
    assert "from LOCKED to PROPOSED" in journal.unjournaled_changes(store)[0]


def test_new_locked_record_without_journal_is_flagged(git_repo: Path) -> None:
    store = Store(git_repo)
    store.create(make_invariant("inv_0000000f", InvStatus.LOCKED))
    assert journal.unjournaled_changes(store) == [
        "inv_0000000f is new and already LOCKED outside the SeamSpec CLI. "
        "Revert it, or ask the user to run `seamspec review`."
    ]


def test_new_proposal_and_new_approval_are_fine(git_repo: Path, human: None) -> None:
    store = Store(git_repo)
    propose(git_repo)
    approved = propose(git_repo)["id"]
    lifecycle.approve(store, load_config(git_repo), approved)
    lifecycle.supersede(
        store, load_config(git_repo), approved, reason="changed my mind"
    )  # absent → LOCKED → SUPERSEDED
    assert journal.unjournaled_changes(store) == []


def test_deleted_locked_record_is_flagged(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    Store(git_repo).path_for(inv_id).unlink()
    assert "record was deleted" in journal.unjournaled_changes(Store(git_repo))[0]


def test_repo_root_in_a_git_subfolder(tmp_path: Path, human: None) -> None:
    sub = tmp_path / "services" / "api"
    sub.mkdir(parents=True)
    (sub / "pyproject.toml").write_text("")
    (sub / "src").mkdir()
    (sub / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    (sub / "src/__init__.py").write_text("")
    from seamspec.installers import scaffold

    scaffold.init(sub)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "Maya Rao")
    git(tmp_path, "config", "user.email", "maya@example.com")
    inv_id = locked_and_committed(sub)
    assert journal.head_statuses(sub) == {inv_id: "LOCKED"}
    flip(Store(sub), inv_id, status=InvStatus.SUPERSEDED, status_reason="x")
    assert journal.unjournaled_changes(Store(sub))


def test_no_git_means_empty_head(py_repo: Path) -> None:
    assert journal.head_statuses(py_repo) == {}


# --- ADRs ----------------------------------------------------------------------------------------


def test_adr_roundtrip_and_status(py_repo: Path) -> None:
    store = Store(py_repo)
    record = adr.create(
        store,
        title="Redis queue: capped backoff!",
        context="Retry storms.",
        decision="Cap at 30s.",
        consequences=["Bounded latency"],
        scopes=["src/queue/**"],
        invariants=[("inv_1a2b3c4d", "Retry delay never exceeds 30 seconds.")],
        today=date(2026, 10, 3),
    )
    assert record.id.startswith("ADR-20261003-")
    assert record.path.name == f"{record.id}-redis-queue-capped-backoff.md"
    parsed = adr.get(store, record.id)
    assert (parsed.title, parsed.status, parsed.scopes, parsed.invariants) == (
        "Redis queue: capped backoff!", "PROPOSED", ["src/queue/**"], ["inv_1a2b3c4d"])  # fmt: skip
    adr.set_status(store, record.id, "SUPERSEDED", superseded_by="ADR-20261005-abcd")
    again = adr.get(store, record.id)
    assert again.status == "SUPERSEDED" and again.superseded_by == "ADR-20261005-abcd"
    assert "## Decision\nCap at 30s." in again.body
    assert f"{record.id}: Redis queue: capped backoff! [SUPERSEDED]" in adr.summary(store)


def test_this_repos_hand_written_adrs_parse() -> None:
    """docs/adr/ uses the same format and moves into .seamspec/adrs/ in week 3 (ADR-20261005-ae6e)."""
    files = sorted((REPO_ROOT / "docs/adr").glob("ADR-*.md"))
    index = (REPO_ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert files
    for path in files:
        record = adr.parse(path.read_text(encoding="utf-8"), path)
        assert path.name.startswith(record.id)
        # PROPOSED designs wait for the owner; the index must show the same status as the file
        assert (
            f"[{record.id}]({path.name})" in index
            and f"| {record.status} |" in index.split(record.id, 1)[1].split("\n", 1)[0]
        )


def test_bad_adrs_are_rejected() -> None:
    with pytest.raises(adr.AdrError, match="frontmatter"):
        adr.parse("# no frontmatter\n")
    with pytest.raises(adr.AdrError, match="bad ADR id"):
        adr.parse("---\nid: ADR-1\ntitle: t\nstatus: PROPOSED\ndate: 2026-10-05\n---\nbody\n")
