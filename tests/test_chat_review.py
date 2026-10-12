"""Approvals in chat: `open_review` through a real MCP client that answers the dialogs (ADR-20261006-c300).

The tests don't set SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE: the chat path must work without a terminal.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp_types import ElicitResult

from seamspec import chat_review
from seamspec.core import hookguard, journal, lifecycle, redgreen, requests, trust
from seamspec.core.config import load_config
from seamspec.core.models import DeadEnd, Invariant, InvStatus
from seamspec.core.store import Store
from seamspec.installers import scaffold
from seamspec.mcp_server import mcp

from .test_lifecycle import propose

Answer = Callable[[str, list[str]], ElicitResult]


@pytest.fixture
def project(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SEAMSPEC_ROOT", str(git_repo))
    monkeypatch.chdir(git_repo)
    monkeypatch.setattr(hookguard, "MANAGED_DIRS", ())
    monkeypatch.setattr(hookguard, "_launch_args", lambda: [])
    chat_review._declined.clear()
    enable_chat_approvals(git_repo)
    return git_repo


def enable_chat_approvals(root: Path) -> None:
    """Off by default (ADR-20261008-5d1e); these tests turn it on, as a project would."""
    cfg = root / ".seamspec/config.toml"
    cfg.write_text(cfg.read_text().replace(scaffold.REVIEW_LINE, "chat_approvals = true\n"))


def pick(choice: str, **fields: Any) -> Answer:
    """The human picks `choice` (the visible value carries the dialog's code) and fills in `fields`."""

    def answer(message: str, choices: list[str]) -> ElicitResult:
        value = next((c for c in choices if c.rsplit("-", 1)[0] == choice), None)
        if value is None:
            raise AssertionError(f"{choice!r} isn't offered: {choices}\n{message}")
        return ElicitResult(action="accept", content={"decision": value, **fields})

    return answer


def closed(action: str = "cancel") -> Answer:
    return lambda message, choices: ElicitResult(action=action)


class Human:
    """Answers dialogs in order and keeps what each one showed."""

    def __init__(self, *answers: Answer) -> None:
        self.answers = list(answers)
        self.shown: list[tuple[str, list[str]]] = []

    async def __call__(self, context: Any, params: Any) -> ElicitResult:
        choices = params.requested_schema["properties"]["decision"]["enum"]
        self.shown.append((params.message, choices))
        if not self.answers:
            raise AssertionError(f"unexpected dialog:\n{params.message}")
        return self.answers.pop(0)(params.message, choices)


def review(human: Human | None, ids: list[str] | None = None) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(mcp, elicitation_callback=human) as client:
            result = await client.call_tool("open_review", {"ids": ids} if ids else {})
            return result.structured_content or json.loads(result.content[0].text)

    return anyio.run(go)


def inv(root: Path, inv_id: str) -> Invariant:
    record = Store(root).get(inv_id)
    assert isinstance(record, Invariant)
    return record


def elicitation_hook(root: Path, matcher: str | None = "*") -> Path:
    path = root / ".claude" / "settings.local.json"
    path.parent.mkdir(exist_ok=True)
    group: dict[str, Any] = {"hooks": [{"type": "command", "command": "echo accept"}]}
    if matcher is not None:
        group["matcher"] = matcher
    path.write_text(json.dumps({"hooks": {"Elicitation": [group]}}))
    return path


# --- approving, rejecting, skipping ----------------------------------------------------------------


def test_approve_in_chat_locks_the_rule_and_records_where(project: Path) -> None:
    inv_id = propose(project)["id"]
    human = Human(pick("approve"))
    out = review(human)
    assert out["reviewed"] == [f"{inv_id}: approved (LOCKED)"] and out["still_waiting"] == 0
    message, choices = human.shown[0]
    assert message.startswith(chat_review.HEADER) and "│ def test_cap():" in message
    assert choices[0].startswith("skip-") and {c.rsplit("-", 1)[0] for c in choices} == {
        "skip", "approve", "reject", "redgreen"}  # fmt: skip
    locked = inv(project, inv_id)
    assert locked.status == InvStatus.LOCKED and locked.decided_via == "chat"
    entry = journal.entries(Store(project))[-1]
    assert entry["to"] == "LOCKED" and entry["via"] == "chat" and entry.get("client")


def test_the_dialog_leads_with_the_summary_and_the_check_list(project: Path) -> None:
    """ADR-20261011-8013: a client that shows only the top of a dialog must show what matters most.
    The check lines are the agent's code, so they carry the quote bar; the full test still follows."""
    propose(project)
    human = Human(pick("skip"))
    review(human)
    message = human.shown[0][0]
    order = [
        "│ Title:",
        "│ Rule:",
        "Test: 5 lines · 1 check",
        "What this test checks (read from the test file by SeamSpec):",
        "│ line 5: assert backoff_delay(100) <= 30",
        "Red-green: not run",
        "Scope:",
        "Why (",
        "Test (.",
    ]
    positions = [message.index(part) for part in order]
    assert positions == sorted(positions), message
    assert "│ def test_cap():" in message  # the whole test, after the summary


def test_reject_needs_a_reason_and_can_record_a_dead_end(project: Path) -> None:
    inv_id = propose(project)["id"]
    human = Human(pick("reject"), pick("reject", reason="Too narrow", also_dead_end=True))
    out = review(human)
    assert "A reason is required to reject" in human.shown[1][0]
    assert out["reviewed"][0].startswith(f"{inv_id}: rejected (Too narrow); recorded as dead end de_")
    rejected = inv(project, inv_id)
    assert rejected.status == InvStatus.REJECTED and rejected.decided_via == "chat"


def test_skipped_items_are_not_offered_again_this_session(project: Path) -> None:
    inv_id = propose(project)["id"]
    assert review(Human(pick("skip")))["reviewed"] == [f"{inv_id}: skipped"]
    out = review(Human())  # Copilot, #43: skipped is still waiting
    assert out["still_waiting"] == 1 and out["message"].startswith("Nothing new to show")
    assert review(Human(pick("skip")), ids=[inv_id])["reviewed"] == [f"{inv_id}: skipped"]  # asked by id
    assert inv(project, inv_id).status == InvStatus.PROPOSED


def test_a_closed_dialog_stops_the_review_and_changes_nothing(project: Path) -> None:
    first, second = propose(project)["id"], propose(project)["id"]
    out = review(Human(closed()))
    assert "dialog was closed" in out["message"] and out["still_waiting"] == 2
    assert {inv(project, i).status for i in (first, second)} == {InvStatus.PROPOSED}


def test_an_answer_without_the_dialog_code_is_refused(project: Path) -> None:
    """A hook that sends a fixed answer ("approve") fails validation: nothing changes."""
    inv_id = propose(project)["id"]
    out = review(Human(lambda m, c: ElicitResult(action="accept", content={"decision": "approve"})))
    assert "didn't match the dialog" in out["message"]
    assert inv(project, inv_id).status == InvStatus.PROPOSED
    assert any(line.get("event") == "chat_answer_rejected" for line in _journal_lines(project))


def test_runner_config_changes_keep_approval_in_the_terminal(project: Path) -> None:
    propose(project)
    (project / ".seamspec/pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n")
    human = Human(pick("skip"))
    review(human)
    message, choices = human.shown[0]
    assert "Runner config changed" in message and not any(c.startswith("approve-") for c in choices)


def test_a_failing_test_is_not_approved(project: Path) -> None:
    inv_id = propose(project, code="def test_fails():\n    assert 1 == 2\n")["id"]
    out = review(Human(pick("approve")))
    assert out["reviewed"][0].startswith(f"{inv_id}: not approved:")
    assert inv(project, inv_id).status == InvStatus.PROPOSED


def test_long_reviews_pause_and_resume(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_review, "MAX_DIALOGS", 2)
    for _ in range(3):
        propose(project)
    out = review(Human(pick("skip"), pick("skip")))
    assert len(out["reviewed"]) == 2 and "call open_review again" in out["message"]


def test_an_answer_never_applies_to_content_changed_after_the_dialog(project: Path) -> None:
    """Copilot, #43: the test is on disk; if it changes while the dialog is open, the answer isn't applied
    and the human sees the new version first."""
    inv_id = propose(project)["id"]
    harness = project / inv(project, inv_id).verification.harness_path

    def swap_test_then_approve(message: str, choices: list[str]) -> ElicitResult:
        harness.write_text(harness.read_text() + "\n\ndef test_more():\n    assert True\n")
        return pick("approve")(message, choices)

    human = Human(swap_test_then_approve, pick("approve"))
    out = review(human)
    assert "changed after the dialog was shown" in human.shown[1][0] and "def test_more" in human.shown[1][0]
    assert out["reviewed"] == [f"{inv_id}: approved (LOCKED)"]  # only after the second, current dialog


def test_a_changed_supersede_reason_is_shown_again(project: Path) -> None:
    store = Store(project)
    old = propose(project)["id"]
    review(Human(pick("approve")))
    lifecycle.request_supersede(store, old, "Raise the cap")

    def change_request_then_supersede(message: str, choices: list[str]) -> ElicitResult:
        lifecycle.request_supersede(store, old, "Remove the cap entirely")
        return pick("supersede")(message, choices)

    human = Human(change_request_then_supersede, pick("skip"))
    review(human)
    assert "Remove the cap entirely" in human.shown[1][0] and inv(project, old).status == InvStatus.LOCKED


def test_a_decline_keeps_decisions_already_made(project: Path) -> None:
    """Copilot, #44: stopping a review never undoes what it already decided."""
    first, second = propose(project)["id"], propose(project)["id"]
    out = review(Human(pick("approve"), closed("decline")))
    assert out["reviewed"] == [f"{first}: approved (LOCKED)"] and "Nothing else changed" in out["message"]
    assert inv(project, first).status == InvStatus.LOCKED and inv(project, second).status == InvStatus.PROPOSED


# --- red-green, supersede requests, dead ends --------------------------------------------------------


def test_red_green_asks_before_running_and_needs_trust(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    propose(project)
    (Store(project).local / trust.TRUST).unlink()  # init trusted this clone; start untrusted
    human = Human(pick("redgreen"), pick("skip"))
    review(human)
    assert "Red-green needs a trusted clone" in human.shown[1][0]
    assert not any(c.startswith("redgreen-") for c in human.shown[1][1])

    store, cfg = Store(project), load_config(project)
    trust.grant(store, cfg, "Maya")
    ran: list[str] = []
    monkeypatch.setattr(redgreen, "check", lambda s, c, i: ran.append(i.id) or redgreen.RedGreen("yes", "fake"))
    chat_review._declined.clear()
    human = Human(pick("redgreen"), pick("dont"), pick("skip"))
    review(human)
    assert "Run this test on your machine?" in human.shown[1][0] and not ran
    assert "Red-green: not run (you chose not to run it)" in human.shown[2][0]
    chat_review._declined.clear()
    human = Human(pick("redgreen"), pick("run"), pick("skip"))
    review(human)
    assert len(ran) == 1 and "Red-green: Fails without your change: YES (fake)" in human.shown[2][0]


def test_replacement_is_approved_in_chat_before_the_old_rule_is_retired(project: Path) -> None:
    """Dogfooding #10: the replacement's dialog comes first; the old rule is retired only once it is locked."""
    store, cfg = Store(project), load_config(project)
    old = propose(project)["id"]
    review(Human(pick("approve")))
    new = propose(project, title="Retry delay is capped at 60s", assertion="Retry delay never exceeds 60 seconds.")[
        "id"
    ]
    lifecycle.request_supersede(store, old, "The SLA allows 60 seconds now", new)
    human = Human(pick("approve"), pick("supersede"))
    out = review(human)
    first, dialog = human.shown[0][0], human.shown[1][0]
    assert f"· {new}" in first and f"Replaces {old} (still locked; retired when its supersede request" in first
    assert "The SLA allows 60 seconds now" in dialog and f"Replacement {new} (LOCKED):" in dialog
    # Copilot, #52: the supersede dialog carries the same readable card for the test that would stop running.
    order = ["The test that would stop running:", "Test: 5 lines · 1 check", "What this test checks",
             "│ line 5: assert backoff_delay(100) <= 30", "│ def test_cap():", "supersede: the rule stops"]  # fmt: skip
    assert [dialog.index(part) for part in order] == sorted(dialog.index(part) for part in order), dialog
    assert out["reviewed"] == [
        f"{new}: approved (LOCKED)",
        f"{old}: superseded by {new} (The SLA allows 60 seconds now)",
    ]
    assert inv(project, old).status == InvStatus.SUPERSEDED and inv(project, old).decided_via == "chat"
    assert inv(project, new).status == InvStatus.LOCKED and not requests.get(store, old)
    assert cfg  # config still loads


def test_chat_cannot_retire_a_rule_whose_replacement_is_not_approved(project: Path) -> None:
    """Skip the replacement: the supersede dialog then offers no "supersede", and says why."""
    store = Store(project)
    old = propose(project)["id"]
    review(Human(pick("approve")))
    new = propose(project, title="Retry delay is capped at 60s", assertion="Retry delay never exceeds 60 seconds.")[
        "id"
    ]
    lifecycle.request_supersede(store, old, "The SLA allows 60 seconds now", new)
    human = Human(pick("skip"), pick("skip"))
    out = review(human, ids=[old])  # asking for the request alone still brings its replacement, first
    assert f"· {new}" in human.shown[0][0]
    dialog, choices = human.shown[1]
    assert "The replacement isn't approved, so this rule can't be retired now" in dialog
    assert "supersede: the rule stops" not in dialog
    assert not any(c.startswith("supersede-") for c in choices) and any(c.startswith("decline-") for c in choices)
    assert out["reviewed"] == [f"{new}: skipped", f"{old}: supersede request skipped"]
    assert inv(project, old).status == InvStatus.LOCKED and inv(project, new).status == InvStatus.PROPOSED


def test_declining_a_supersede_needs_a_reason_the_agent_sees(project: Path) -> None:
    old = propose(project)["id"]
    review(Human(pick("approve")))
    lifecycle.request_supersede(Store(project), old, "Remove the cap")
    out = review(Human(pick("decline"), pick("decline", reason="The cap is a contract")))
    assert out["reviewed"] == [f"{old}: supersede declined, the rule stays locked (The cap is a contract)"]
    assert inv(project, old).status == InvStatus.LOCKED


def test_dead_ends_keep_or_retire(project: Path) -> None:
    from .conftest import make_dead_end

    store = Store(project)
    store.create(make_dead_end("de_00000001"))
    store.create(make_dead_end("de_00000002"))
    human = Human(pick("keep"), pick("wrong"), pick("wrong", reason="Fixed upstream"))
    out = review(human)
    assert out["reviewed"] == ["de_00000001: kept", "de_00000002: retired (Fixed upstream)"]
    retired = store.get("de_00000002")
    assert isinstance(retired, DeadEnd) and retired.status == "RETIRED" and retired.decided_via == "chat"
    entry = journal.entries(store)[-1]  # Copilot, #43: journaled like every human decision
    assert (entry["id"], entry["from"], entry["to"], entry["via"]) == ("de_00000002", "ACTIVE", "RETIRED", "chat")
    assert entry.get("client")
    assert review(Human())["message"] == "Nothing waits for review."  # both seen: no longer new


# --- guards --------------------------------------------------------------------------------------


@pytest.mark.parametrize("matcher", [None, "*", "plugin:seamspec:seamspec", "plugin:.*"])
def test_a_hook_that_could_answer_refuses_chat_approvals(project: Path, matcher: str | None) -> None:
    inv_id = propose(project)["id"]
    elicitation_hook(project, matcher)
    human = Human()
    out = review(human)
    assert not human.shown and "won't take approvals in chat" in out["message"] and "seamspec review" in out["message"]
    assert inv(project, inv_id).status == InvStatus.PROPOSED


def test_a_hook_for_another_server_is_fine(project: Path) -> None:
    propose(project)
    elicitation_hook(project, "seamspec|other-server")  # exact names: neither is SeamSpec's server
    assert review(Human(pick("approve")))["reviewed"][0].endswith("approved (LOCKED)")


def test_a_hook_added_while_the_dialog_is_open_stops_the_answer(project: Path) -> None:
    inv_id = propose(project)["id"]

    def add_hook_then_approve(message: str, choices: list[str]) -> ElicitResult:
        elicitation_hook(project)
        return pick("approve")(message, choices)

    out = review(Human(add_hook_then_approve))
    assert "won't take approvals in chat" in out["message"] and out["reviewed"] == []
    assert inv(project, inv_id).status == InvStatus.PROPOSED


@pytest.mark.parametrize("mode", ["advisory", "enforced", "strict"])
def test_chat_approvals_are_off_by_default(git_repo: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """ADR-20261008-5d1e: Claude Code doesn't show the whole dialog yet (verification 2)."""
    monkeypatch.setenv("SEAMSPEC_ROOT", str(git_repo))
    propose(git_repo)
    cfg = git_repo / ".seamspec/config.toml"
    cfg.write_text(cfg.read_text().replace('mode = "enforced"', f'mode = "{mode}"', 1))
    human = Human()
    out = review(human)
    assert out["error"] == "chat_approvals_off" and "seamspec review" in out["message"] and not human.shown


def test_a_declined_dialog_stops_the_review(project: Path) -> None:
    """Verification 2: the desktop app declined every dialog without showing it. A decline must not
    count as the human skipping each item; the review stops and says why."""
    first, second = propose(project)["id"], propose(project)["id"]
    human = Human(closed("decline"))
    out = review(human)
    assert len(human.shown) == 1 and out["reviewed"] == [] and "If no dialog appeared" in out["message"]
    assert {inv(project, i).status for i in (first, second)} == {InvStatus.PROPOSED}
    assert any(line.get("event") == "chat_dialog_declined" for line in _journal_lines(project))
    assert review(Human(pick("skip"), pick("skip")))["reviewed"] == [f"{first}: skipped", f"{second}: skipped"]


def test_a_client_without_dialogs_falls_back_to_the_terminal(project: Path) -> None:
    propose(project)
    out = review(None)
    assert out["error"] == "no_dialogs" and "seamspec review" in out["message"]


def _journal_lines(root: Path) -> list[dict[str, Any]]:
    path = Store(root).local / journal.JOURNAL
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
