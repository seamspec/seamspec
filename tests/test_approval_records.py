"""What an approval commits (ADR-20261105-a7d2, SessionWalk dogfooding).

`approved_by` is the git identity, saved in a record that is committed and locked, so a personal email
gets a warning before it is recorded. A locked rule's details are frozen; the local checks (Stop,
pre-commit, `doctor`) now compare them with HEAD, as `doctor --ci` does with the base branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import doctor, journal, lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .conftest import git
from .test_chat_review import Human, pick, project, review  # noqa: F401  (project is a fixture)
from .test_journal_adr import flip, locked_and_committed
from .test_lifecycle import propose

runner = CliRunner()


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


@pytest.fixture
def gmail(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Maya Rao")  # CI runners have no git user name to fall back on
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "maya.rao@gmail.com")
    return "maya.rao@gmail.com"


# --- the personal-email warning ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity,personal",
    [
        ("Maya Rao <maya.rao@gmail.com>", True),
        ("Maya Rao <Maya@GMail.com>", True),
        ("Maya Rao <maya@yahoo.co.uk>", True),
        ("Maya Rao <maya@hotmail.fr>", True),
        ("Maya Rao <maya@proton.me>", True),
        ("Maya Rao <12345+maya@users.noreply.github.com>", False),
        ("Maya Rao <maya@acme.com>", False),  # a work address in a work repo is expected
        ("Maya Rao <maya@mail.gmail.com.example.org>", False),
        ("Maya Rao <maya@outlook.acme.com>", False),  # Copilot on #112: a company host, not the provider
        ("Maya Rao <maya@yahoo.com.example.org>", False),
        ("maya", False),  # git couldn't say: the OS user name, no email
    ],
)
def test_personal_email_is_told_apart(identity: str, personal: bool) -> None:
    assert (lifecycle.personal_email(identity) is not None) is personal
    assert (lifecycle.identity_warning(identity) is not None) is personal


def test_the_warning_names_the_address_and_the_fix() -> None:
    warning = lifecycle.identity_warning("Maya Rao <maya.rao@gmail.com>")
    assert warning is not None
    assert "maya.rao@gmail.com" in warning and "can't be edited afterwards" in warning
    assert "git config user.email" in warning and "noreply" in warning


def test_review_warns_before_anything_is_decided_and_can_stop(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None, gmail: str
) -> None:
    monkeypatch.chdir(git_repo)
    inv_id = propose(git_repo)["id"]
    out = runner.invoke(app, ["review"], input="n\n")
    assert out.exit_code == 0, out.output
    assert f"Note: Approving records your git identity, {gmail}" in out.output
    assert "Stopped before anything was decided." in out.output
    assert "[a]pprove" not in out.output  # no proposal was shown
    assert Store(git_repo).get(inv_id).status == InvStatus.PROPOSED


def test_review_goes_on_when_the_address_is_kept(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None, gmail: str
) -> None:
    monkeypatch.chdir(git_repo)
    inv_id = propose(git_repo)["id"]
    out = runner.invoke(app, ["review"], input="\nn\na\n")  # keep the address, skip red-green, approve
    assert out.exit_code == 0, out.output
    record = Store(git_repo).get(inv_id)
    assert record.status == InvStatus.LOCKED and gmail in (record.approved_by or "")


def test_review_says_nothing_for_a_noreply_address(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None
) -> None:
    monkeypatch.chdir(git_repo)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "12345+maya@users.noreply.github.com")
    propose(git_repo)
    out = runner.invoke(app, ["review"], input="n\ns\n")
    assert "Approving records your git identity" not in out.output
    assert "Continue with this address?" not in out.output


def test_approve_warns_and_can_stop(git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None, gmail: str) -> None:
    """Copilot on #112: `seamspec approve <id>` locks a rule too, so it warns the same way."""
    monkeypatch.chdir(git_repo)
    inv_id = propose(git_repo)["id"]
    out = runner.invoke(app, ["approve", inv_id], input="n\n")
    assert out.exit_code == 1
    assert f"Note: Approving records your git identity, {gmail}" in out.output
    assert "not approved: set the address" in out.output
    assert Store(git_repo).get(inv_id).status == InvStatus.PROPOSED
    kept = runner.invoke(app, ["approve", inv_id], input="y\ny\n")  # keep the address, then lock it
    assert kept.exit_code == 0, kept.output
    assert Store(git_repo).get(inv_id).status == InvStatus.LOCKED


def test_the_chat_dialog_shows_the_warning(project: Path, gmail: str) -> None:  # noqa: F811
    propose(project)
    human = Human(pick("skip"))
    review(human)
    assert f"Note: Approving records your git identity, {gmail}" in human.shown[0][0]


def test_init_mentions_a_personal_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gmail: str) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--mode", "advisory", "--no-claude-md"])
    assert result.exit_code == 0, result.output
    assert f"note: Approving records your git identity, {gmail}" in result.output


# --- frozen fields, compared with HEAD -----------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "A friendlier title"),
        ("approved_by", "Maya Rao <12345+maya@users.noreply.github.com>"),
        ("scope", {"paths": ["src/**"]}),
    ],
)
def test_a_hand_edit_to_a_locked_rule_is_caught_locally(git_repo: Path, human: None, field: str, value) -> None:
    inv_id = locked_and_committed(git_repo)
    store = Store(git_repo)
    if field == "scope":
        value = store.get(inv_id).scope.model_copy(update=value)
    flip(store, inv_id, **{field: value})
    problems = journal.unjournaled_changes(store)
    assert problems == [
        f"{inv_id} is LOCKED and its {field} changed since HEAD. Only a supersede may change a locked rule: "
        f"revert the edit (`git checkout HEAD -- .seamspec/invariants/{inv_id}.json`)."
    ]
    report = doctor.run(git_repo)
    assert any(f.check == "journal" and f.level == "error" and field in f.message for f in report.findings)


def test_marking_a_locked_rule_critical_is_not_an_edit(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    lifecycle.set_critical(Store(git_repo), inv_id, True)
    assert journal.unjournaled_changes(Store(git_repo)) == []


def test_a_supersede_through_the_cli_is_not_an_edit(git_repo: Path, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    lifecycle.supersede(Store(git_repo), load_config(git_repo), inv_id, reason="requirement changed")
    assert journal.unjournaled_changes(Store(git_repo)) == []


def test_the_commit_check_blocks_a_hand_edit(git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None) -> None:
    inv_id = locked_and_committed(git_repo)
    flip(Store(git_repo), inv_id, title="A friendlier title")
    git(git_repo, "add", "-A")
    monkeypatch.chdir(git_repo)
    out = runner.invoke(app, ["verify", "--gate"])
    assert out.exit_code != 0
    assert f"{inv_id} is LOCKED and its title changed since HEAD" in out.output
