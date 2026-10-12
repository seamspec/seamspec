"""Approvals in chat: the `open_review` MCP tool (ADR-20261006-c300, SPEC §14.1).

The agent calls `open_review(ids?)`; SeamSpec shows the human one form dialog per item, rendered
from the ledger (the agent never supplies the text), and acts on the human's answer through the same
lifecycle functions as `seamspec review`, recording `decided_via: "chat"`. The agent only gets the
outcomes. Same order as the terminal: new dead ends, supersede requests, proposed rules.

On protocol 2026-07-28 a dialog is an `InputRequiredResult`: Claude Code shows it, then calls the
tool again with the answer and the sealed `request_state` (the SDK encrypts and authenticates it, so
the agent and the client can't forge it). Each call is one round.

Guards (all from the ADR):
1. No hook may intercept the dialogs: `hookguard.scan` runs at the start of every round, so before
   each dialog and again before acting on an answer. Each dialog's choices carry a random code, so a
   hook that sends a fixed answer fails validation and the review stops.
2. Only when a human can answer: the client must declare form dialogs; a closed dialog stops the
   review (a declined one too: the desktop app declines unseen); an item the human skips isn't offered
   again in this session unless asked for by id.
3. Provenance: records get `decided_via`, the journal gets `via` and the client's name.
5. Same rules as the terminal: runner config changes still need `seamspec review` in a terminal,
   and approving still runs the test. Red-green runs only after its own "run this test?" yes, and
   only in a trusted clone.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import string
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp_types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from . import review
from .core import hookguard, journal, lifecycle, redgreen, requests, testview, trust, verifier
from .core.config import Config
from .core.models import DeadEnd, Invariant, InvStatus
from .core.store import Store

PROTOCOL = "2026-07-28"  # dialogs ride InputRequiredResult from this revision on
MAX_DIALOGS = 8  # per tool call: the client retries the call once per dialog, and clients cap that
HEADER = "From SeamSpec, not the agent. The agent can't answer this dialog."
FALLBACK = "Ask the user to run `seamspec review` in a terminal."
KIND_NAMES = {"de": "Dead end", "sup": "Supersede request", "inv": "Proposed rule"}

_declined: set[str] = set()  # skipped in this server process, i.e. this session


def _code() -> str:
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))


def _quote(text: str) -> str:
    """Agent-written text, marked line by line so it can't pass for SeamSpec's own words."""
    return "\n".join(f"│ {line}" for line in (text.splitlines() or [""]))


def _queue(store: Store, ids: list[str] | None) -> list[list[str]]:
    dead_ends, reqs, proposals = review.pending(store)
    items = [["de", d.id] for d in dead_ends] + [["sup", r.invariant_id] for r in reqs]
    items += [["inv", i.id] for i in proposals]
    if ids:
        wanted = set(ids)
        return [item for item in items if item[1] in wanted]
    return [item for item in items if item[1] not in _declined]


def _still_pending(store: Store, kind: str, item_id: str) -> bool:
    try:
        record = store.get(item_id)
    except KeyError:
        return False
    if kind == "de":
        return isinstance(record, DeadEnd) and record.status == "ACTIVE"
    if kind == "sup":
        return item_id in requests.pending_supersede_ids(store)
    return isinstance(record, Invariant) and record.status == InvStatus.PROPOSED


# --- dialogs -------------------------------------------------------------------------------------


def _schema(choices: list[str], code: str, reason_title: str | None, dead_end_box: bool = False) -> dict[str, Any]:
    props: dict[str, Any] = {
        "decision": {"type": "string", "title": "Decision", "enum": [f"{c}-{code}" for c in choices]},
    }
    if reason_title:
        props["reason"] = {"type": "string", "title": reason_title}
    if dead_end_box:
        props["also_dead_end"] = {"type": "boolean", "title": "Also record it as a dead end (reject only)",
                                  "default": False}  # fmt: skip
    return {"type": "object", "properties": props, "required": ["decision"]}


def _choices(store: Store, cfg: Config, state: dict[str, Any]) -> list[str]:
    kind, phase = state["queue"][state["i"]][0], state["phase"]
    if phase == "run":
        return ["dont", "run"]
    if kind == "de":
        return ["skip", "keep", "wrong"]
    if kind == "sup":
        return ["skip", "supersede", "decline"]
    choices = ["skip"]  # first: a hook that picks the first choice changes nothing
    if not verifier.check_fingerprints(store.root, cfg):
        choices.append("approve")
    choices.append("reject")
    if state.get("rg") is None:
        choices.append("redgreen")
    return choices


def _position(state: dict[str, Any]) -> str:
    kind, item_id = state["queue"][state["i"]]
    return f"{KIND_NAMES[kind]} {state['i'] + 1} of {len(state['queue'])} · {item_id}"


def _test_text(store: Store, inv: Invariant) -> str:
    harness = store.root / inv.verification.harness_path
    code = harness.read_text(encoding="utf-8") if harness.is_file() else "(the test file is missing)"
    return f"Test ({inv.verification.harness_path}, runner {inv.verification.runner}):\n{_quote(code)}"


def _checks_text(store: Store, inv: Invariant) -> list[str]:
    """What the test checks, read from the test file by SeamSpec. The check lines are the agent's
    code, so each carries the quote bar; the counts and warnings are SeamSpec's own words."""
    harness = store.root / inv.verification.harness_path
    if not harness.is_file():
        return []
    view = testview.analyze(harness.read_text(encoding="utf-8"), inv.verification.runner)
    how = "read from the test file by SeamSpec" if view.parsed else "lines that look like checks"
    lines = [f"Test: {view.facts()}", *(f"Warning: {w}" for w in view.warnings)]
    if view.checks:
        lines += [f"What this test checks ({how}):", *(_quote(f"line {c.line}: {c.text}") for c in view.checks)]
    return lines


def _message(store: Store, cfg: Config, state: dict[str, Any]) -> str:
    kind, item_id = state["queue"][state["i"]]
    record = store.get(item_id)
    lines = [HEADER, "", _position(state), 'Lines starting with "│" are written by the agent, shown as is.']
    if state.get("note"):
        lines += ["", f"Note: {state['note']}"]
    if state["phase"] == "run":
        assert isinstance(record, Invariant)
        lines += ["", "Run this test on your machine? It runs with your permissions.",
                  "It runs twice: on your working tree and on the last commit (red-green check).",
                  "", _test_text(store, record),
                  "", "Choose run-… to run it, dont-… to go back without running it."]  # fmt: skip
        return "\n".join(lines)
    if kind == "de":
        assert isinstance(record, DeadEnd)
        lines += ["", f"Recorded by: {record.source}, {record.created_at.date().isoformat()}",
                  f"Scope: {', '.join(record.scope.paths)}", "Tried:", _quote(record.approach),
                  "Why it failed:", _quote(record.failure_symptom), "",
                  "keep: the agent goes on avoiding this approach. wrong: retire it (give a reason)."]  # fmt: skip
    elif kind == "sup":
        assert isinstance(record, Invariant)
        req = requests.get(store, item_id)
        lines += ["", "The agent asks to retire this locked rule:", _quote(f"{record.title}: {record.assertion}"),
                  f"Scope: {', '.join(record.scope.paths)}", "Reason given:",
                  _quote(req.reason if req else "")]  # fmt: skip
        if req and req.replacement_id:
            rep = store.get(req.replacement_id)
            if isinstance(rep, Invariant):
                lines += [f"Replacement {rep.id} ({rep.status.value}):", _quote(f"{rep.title}: {rep.assertion}")]
                if rep.status == InvStatus.PROPOSED:
                    lines.append("The replacement needs its own approval; it's shown after this one.")
        # The same readable card as a proposal (ADR-20261011-8013 item 7): what would stop being
        # checked is the old rule's test, so the reviewer sees its check list and the test itself.
        lines += ["", "The test that would stop running:", *_checks_text(store, record), "",
                  _test_text(store, record)]  # fmt: skip
        lines += ["", "supersede: the rule stops being enforced and its test moves out of the test tree.",
                  "decline: the rule stays locked (give a reason; the agent sees it)."]  # fmt: skip
    else:
        assert isinstance(record, Invariant)
        # Summary and check list first (ADR-20261011-8013): a client that shows only the top of a
        # dialog then shows the part that matters most. The full test still follows.
        lines += ["", _quote(f"Title: {record.title}"), _quote(f"Rule: {record.assertion}"),
                  *_checks_text(store, record), f"Red-green: {state.get('rg') or 'not run'}",
                  f"Scope: {', '.join(record.scope.paths)}", f"Why ({record.origin.type}):",
                  _quote(review.cut(record.origin.text, 600)), "", _test_text(store, record)]  # fmt: skip
        if verifier.check_fingerprints(store.root, cfg):
            lines.append("Runner config changed since it was last confirmed: approve in a terminal "
                         "(`seamspec review`) after checking it.")  # fmt: skip
        lines += ["", "approve: SeamSpec runs the test now and, if it passes, locks the rule: from then on "
                  "it runs at every stop, commit and CI run.", "reject: give a reason; the agent sees it."]  # fmt: skip
        if state.get("rg") is None:
            lines.append("redgreen: asks before running the test, to see if it fails without the change.")
    return "\n".join(lines)


def _rendered(store: Store, cfg: Config, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The dialog for the current item and phase: its message and its form."""
    kind = state["queue"][state["i"]][0]
    if state["phase"] == "run":
        reason = None
    else:
        reason = {"de": "Reason (required for wrong)", "sup": "Reason (required to decline)",
                  "inv": "Reason (required to reject)"}[kind]  # fmt: skip
    schema = _schema(_choices(store, cfg, state), state["code"], reason, kind == "inv" and state["phase"] == "decide")
    return _message(store, cfg, state), schema


def _digest(store: Store, cfg: Config, state: dict[str, Any]) -> str:
    message, schema = _rendered(store, cfg, state)
    return hashlib.sha256((message + json.dumps(schema, sort_keys=True)).encode("utf-8")).hexdigest()


def _unchanged(store: Store, cfg: Config, state: dict[str, Any]) -> bool:
    """Is the dialog the human answered still what SeamSpec would show now? (Copilot, #43) The test, the
    request and the record are on disk, so another process could change them while the dialog is open;
    the answer must never apply to something the human didn't see."""
    try:
        return _digest(store, cfg, state) == state.get("shown")
    except (KeyError, OSError):
        return False


def _dialog(store: Store, cfg: Config, state: dict[str, Any]) -> InputRequiredResult:
    message, schema = _rendered(store, cfg, state)
    state["shown"] = _digest(store, cfg, state)
    state["key"] = f"q{state['n']}"
    state["n"] += 1
    request = ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=schema))
    return InputRequiredResult(input_requests={state["key"]: request}, request_state=json.dumps(state))


# --- answers -------------------------------------------------------------------------------------


class Stop(Exception):
    """End the review now; the message goes to the agent."""


def _next(state: dict[str, Any], outcome: str | None) -> None:
    if outcome:
        state["out"].append(outcome)
    state.update(i=state["i"] + 1, phase="decide", note=None, rg=None, code=_code())


def _apply(store: Store, cfg: Config, state: dict[str, Any], answer: object, client: str | None) -> None:
    kind, item_id = state["queue"][state["i"]]
    if not isinstance(answer, ElicitResult) or answer.action == "cancel":
        raise Stop("The dialog was closed, so the review stopped. Nothing else changed.")
    if answer.action == "decline":  # the form's own Decline button, or an app that declines unseen
        journal.note(store, "chat_dialog_declined", item=item_id, client=client)
        raise Stop("The dialog was declined, so the review stopped. Nothing else changed. If no dialog "
                   f"appeared, this app can't show SeamSpec's dialogs. {FALLBACK}")  # fmt: skip
    content = answer.content or {}
    allowed = {f"{c}-{state['code']}": c for c in _choices(store, cfg, state)}
    choice = allowed.get(str(content.get("decision")))
    if choice is None:
        journal.note(store, "chat_answer_rejected", item=item_id, client=client)
        raise Stop(f"An answer for {item_id} didn't match the dialog SeamSpec showed (a hook may have answered "
                   f"it), so nothing was changed for it and the review stopped. {FALLBACK}")  # fmt: skip
    if not _still_pending(store, kind, item_id):
        return _next(state, None)  # decided elsewhere meanwhile: nothing to apply
    if not _unchanged(store, cfg, state):
        state["note"] = "This item changed after the dialog was shown, so your answer wasn't applied. Here it is again."
        return None
    reason = str(content.get("reason") or "").strip()
    handlers: dict[str, Callable[[], None]] = {
        "de": lambda: _apply_dead_end(store, state, item_id, choice, reason, client),
        "sup": lambda: _apply_supersede(store, cfg, state, item_id, choice, reason, client),
        "inv": lambda: _apply_proposal(store, cfg, state, item_id, choice, reason, content, client),
    }
    handlers[kind]()


def _apply_dead_end(store: Store, state: dict[str, Any], de_id: str, choice: str, reason: str,
                    client: str | None) -> None:  # fmt: skip
    if choice == "skip":
        _declined.add(de_id)
        return _next(state, f"{de_id}: skipped")
    if choice == "wrong" and not reason:
        state["note"] = "A reason is required to retire a dead end."
        return None
    if choice == "wrong":
        lifecycle.retire_dead_end(store, de_id, reason, via="chat", client=client)
    review.mark_dead_end_seen(store, de_id)
    return _next(state, f"{de_id}: retired ({reason})" if choice == "wrong" else f"{de_id}: kept")


def _apply_supersede(store: Store, cfg: Config, state: dict[str, Any], inv_id: str, choice: str, reason: str,
                     client: str | None) -> None:  # fmt: skip
    if choice == "skip":
        _declined.add(inv_id)
        return _next(state, f"{inv_id}: supersede request skipped")
    if choice == "decline":
        if not reason:
            state["note"] = "A reason is required to decline: the agent sees it."
            return None
        requests.clear(store, inv_id)
        return _next(state, f"{inv_id}: supersede declined, the rule stays locked ({reason})")
    req = requests.get(store, inv_id)
    out = lifecycle.supersede(store, cfg, inv_id, via="chat", client=client)
    rep = out.get("superseded_by")
    if rep and ["inv", rep] not in state["queue"][state["i"] + 1 :] and _still_pending(store, "inv", rep):
        state["queue"].append(["inv", rep])  # the replacement still needs its own approval
    return _next(state, f"{inv_id}: superseded" + (f" by {rep}" if rep else "") + (f" ({req.reason})" if req else ""))


def _apply_proposal(store: Store, cfg: Config, state: dict[str, Any], inv_id: str, choice: str, reason: str,
                    content: dict[str, Any], client: str | None) -> None:  # fmt: skip
    if state["phase"] == "run":
        state["phase"] = "decide"
        if choice == "run":
            inv = store.get(inv_id)
            assert isinstance(inv, Invariant)
            state["rg"] = redgreen.check(store, cfg, inv).line()
        else:
            state["rg"] = "not run (you chose not to run it)"
        return None
    if choice == "skip":
        _declined.add(inv_id)
        return _next(state, f"{inv_id}: skipped")
    if choice == "redgreen":
        st = trust.state(store, cfg)
        if not st.trusted:
            state["note"] = f"Red-green needs a trusted clone ({st.reason}): run `seamspec trust` in a terminal first."
            state["rg"] = "not available in an untrusted clone"
            return None
        state["phase"] = "run"
        return None
    if choice == "reject":
        if not reason:
            state["note"] = "A reason is required to reject: the agent sees it."
            return None
        out = lifecycle.reject(store, cfg, inv_id, reason, as_dead_end=content.get("also_dead_end") is True,
                               via="chat", client=client)  # fmt: skip
        extra = f"; recorded as dead end {out['dead_end']}" if "dead_end" in out else ""
        return _next(state, f"{inv_id}: rejected ({reason}){extra}")
    try:
        lifecycle.approve(store, cfg, inv_id, via="chat", client=client)
    except lifecycle.LifecycleError as exc:
        return _next(state, f"{inv_id}: not approved: {str(exc).splitlines()[0]}")
    return _next(state, f"{inv_id}: approved (LOCKED)")


# --- one round -----------------------------------------------------------------------------------


def _finish(store: Store, state: dict[str, Any], message: str | None = None) -> dict[str, Any]:
    left = sum(len(group) for group in review.pending(store))
    out: dict[str, Any] = {"reviewed": state["out"], "still_waiting": left}
    if message:
        out["message"] = message
    elif left:
        out["message"] = f"{left} item(s) still wait for review (skipped ones aren't offered again this session)."
    return out


def step(
    store: Store,
    cfg: Config,
    ids: list[str] | None,
    request_state: str | None,
    answers: dict[str, object] | None,
    client: str | None,
    project_dirs: list[Path],
) -> dict[str, Any] | InputRequiredResult:
    """One round of `open_review`: act on the answer to the last dialog, then show the next one."""
    state: dict[str, Any] = (
        json.loads(request_state)
        if request_state
        else {"queue": _queue(store, ids), "i": 0, "n": 0, "phase": "decide", "out": [], "code": _code()}
    )
    if not state["queue"]:
        if not any(review.pending(store)):
            return {"reviewed": [], "still_waiting": 0, "message": "Nothing waits for review."}
        return _finish(store, state, "Nothing new to show: what's waiting was skipped earlier in this session "
                       "(or isn't among the ids asked for). Ask for an item by id to see it again.")  # fmt: skip
    problems = hookguard.scan(project_dirs)
    if problems:
        journal.note(store, "chat_review_refused", problems=problems, client=client)
        return _finish(store, state, "SeamSpec won't take approvals in chat while a hook could answer or change "
                       f"its dialogs: {'; '.join(problems)}. {FALLBACK}")  # fmt: skip
    try:
        if request_state:
            _apply(store, cfg, state, (answers or {}).get(state.get("key", "")), client)
    except Stop as stop:
        return _finish(store, state, str(stop))
    except lifecycle.LifecycleError as exc:
        _next(state, f"{state['queue'][state['i']][1]}: not changed: {str(exc).splitlines()[0]}")
    while state["i"] < len(state["queue"]) and not _still_pending(store, *state["queue"][state["i"]]):
        _next(state, None)  # decided elsewhere meanwhile
    if state["i"] >= len(state["queue"]):
        return _finish(store, state)
    if state["n"] >= MAX_DIALOGS:
        return _finish(store, state, "Paused after several dialogs: call open_review again to go on.")
    return _dialog(store, cfg, state)


def can_show_dialogs(protocol_version: str | None, capabilities: object) -> bool:
    elicitation = getattr(capabilities, "elicitation", None)
    form_ok = elicitation is not None and (elicitation.form is not None or elicitation.url is None)
    return form_ok and protocol_version is not None and protocol_version >= PROTOCOL
