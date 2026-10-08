"""Claude Code hook adapter (SPEC §7.2, §16.1).

Entry point: `seamspec hook claude <event>` with the hook payload on stdin. Decisions travel in the
JSON printed to stdout; the exit code is always 0, so a crash in SeamSpec can't be mistaken for a
"block" (exit code 2) by the host.

- `pre-tool-use` (Edit / Write / MultiEdit / NotebookEdit): blocks direct edits to the ledger, rule
  tests and runner config, and shows the agent the rules and dead ends for a governed file the first
  time it edits it (as `additionalContext`, no permission decision, so the user's own permission
  settings still apply). A brand-new file in a governed path is denied once instead.
- `stop`: runs the LOCKED rules (within one deadline) and the journal check, and blocks finishing
  while something fails, at most `verify.max_stop_retries` times per user prompt.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from ..core import journal, verifier
from ..core.config import MAX_STOP_DEADLINE, Config, load_config
from ..core.context import constraints_for
from ..core.models import DeadEnd, Invariant, InvStatus
from ..core.requests import pending_supersede_ids
from ..core.root import find_root, to_rel
from ..core.scope import effective_protected_paths, matches
from ..core.session import SessionState
from ..core.store import Store
from ..core.tree import changed_files, tree_fingerprint
from ..core.trust import execution_permitted

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PROTECTED_MESSAGE = (
    "SeamSpec: direct edits to SeamSpec records, rule tests and runner config are blocked. "
    "Use the SeamSpec tools (propose_invariant, log_dead_end, request_supersede) or the seamspec CLI."
)
SUPERSEDE_HINT = (
    "Fix the regression. If this behavior change is intentional, call "
    "request_supersede(invariant_id, reason, replacement_id) and tell the user."
)


def _pre_tool(**fields: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **fields}}


def _deny(reason: str) -> dict[str, Any]:
    return _pre_tool(permissionDecision="deny", permissionDecisionReason=reason)


def _context(text: str) -> dict[str, Any]:
    # No permissionDecision at all: never "allow", which would skip the user's permission prompts (§7.2).
    return _pre_tool(additionalContext=text)


def _edited_path(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input") or {}
    value = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(value, str) or not value:
        return None
    if not Path(value).is_absolute() and payload.get("cwd"):
        value = str(Path(payload["cwd"]) / value)
    return value


def pre_tool_use(payload: dict[str, Any], store: Store, cfg: Config) -> dict[str, Any] | None:
    if cfg.mode == "advisory" or payload.get("tool_name") not in EDIT_TOOLS:
        return None
    file_path = _edited_path(payload)
    if file_path is None:
        return None
    rel = to_rel(store.root, file_path)
    if rel is None:
        return None
    # Ledger protection (§7.1 layer 3) holds in every gate mode.
    if matches(effective_protected_paths(cfg), rel):
        return _deny(PROTECTED_MESSAGE)
    if cfg.hooks.gate_mode == "off":
        return None

    cs = constraints_for(store, [rel])
    if cs.empty:
        return None
    state = SessionState.load(store, str(payload.get("session_id") or "unknown"))
    key = f"{rel}:{store.revision()}"
    if key in state.acknowledged:
        return None
    state.acknowledged.append(key)
    state.save(store)
    text = f"SeamSpec: {rel} is governed by:\n{cs.render()}"
    if cfg.hooks.gate_mode == "deny_once" or not (store.root / rel).exists():  # brand-new file
        return _deny(text + "\nRe-attempt the edit once your change respects these constraints.")
    return _context(text + "\nMake sure this edit respects the locked rules.")


def _retry_key(payload: dict[str, Any]) -> str:
    """One retry budget per user prompt. Older Claude Code versions send `stop_hook_active` instead
    of `prompt_id`; there, a fresh stop (not caused by our own block) starts a new budget."""
    return str(payload.get("prompt_id") or "session")


def _block(state: SessionState, store: Store, cfg: Config, key: str, details: str) -> dict[str, Any]:
    """Block finishing, capped by max_stop_retries so the agent can never be trapped in a Stop loop."""
    used = state.stop_retries.get(key, 0)
    if used >= cfg.verify.max_stop_retries:
        state.save(store)
        return {
            "systemMessage": f"SeamSpec: still failing after {used} attempts. "
            "Pre-commit and CI will block this change.\n" + details[:500]
        }
    state.stop_retries[key] = used + 1
    state.save(store)
    return {"decision": "block", "reason": f"{details}\nAttempt {used + 1} of {cfg.verify.max_stop_retries}."}


def _start_retries(payload: dict[str, Any], state: SessionState) -> str:
    key = _retry_key(payload)
    if "prompt_id" not in payload and payload.get("stop_hook_active") is False:
        state.stop_retries.pop(key, None)
    return key


def stop(payload: dict[str, Any], store: Store, cfg: Config) -> dict[str, Any] | None:
    if cfg.mode == "advisory":
        return None
    budget = min(cfg.verify.stop_deadline_seconds, MAX_STOP_DEADLINE)  # belt and braces: config is validated too
    deadline = time.monotonic() + budget  # always below the hook timeout (§16.1)
    state = SessionState.load(store, str(payload.get("session_id") or "unknown"))
    key = _start_retries(payload, state)

    allowed, why = execution_permitted(store, cfg)
    if not allowed:
        state.save(store)
        return {"systemMessage": f"SeamSpec: locked rules were not checked: {why}."}

    journal_problems = journal.unjournaled_changes(store)  # e.g. a rule set to SUPERSEDED with Bash
    fingerprint = tree_fingerprint(store.root)
    if not journal_problems and fingerprint is not None and fingerprint == state.last_green_fingerprint:
        state.save(store)
        return None

    locked = [i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
    selection = cfg.verify.run_on_stop
    if selection == "auto":
        selection = "all" if len(locked) < cfg.verify.stop_all_threshold else "scoped"
    if selection == "scoped":  # pre-commit and CI still run all
        changed = changed_files(store.root)
        if changed is not None:
            locked = [i for i in locked if any(matches(i.scope.paths, f) for f in changed)]
    report = verifier.run(store.root, cfg, locked, deadline=deadline)
    verifier.save_last(store.root, report)

    if report.passed and not journal_problems:
        state.last_green_fingerprint = fingerprint
        state.stop_retries.pop(key, None)
        state.save(store)
        return None

    failing = set(report.failing_ids)
    other = journal_problems + report.config_failures
    if report.incomplete and not failing and not other and not cfg.hooks.fail_closed:
        state.save(store)
        return {
            "systemMessage": "SeamSpec: time ran out before every locked rule was checked. "
            "Pre-commit will run the full set."
        }
    strict_incomplete = report.incomplete and cfg.hooks.fail_closed  # strict: a cut-short run is a failure
    if failing and failing <= pending_supersede_ids(store) and not other and not strict_incomplete:
        state.save(store)
        return {
            "systemMessage": "SeamSpec: supersede requested for "
            f"{', '.join(sorted(failing))}. Run `seamspec review` to approve or decline it."
        }

    lines = (
        other
        + report.integrity_failures
        + [
            f"[FAIL] {', '.join(r.failed_ids or r.invariant_ids)} ({r.runner})\n{r.output}"
            for r in report.results
            if not r.passed and not r.incomplete
        ]
    )
    if report.incomplete:
        lines.append("[INCOMPLETE] time ran out before every locked rule was checked.")
    return _block(
        state, store, cfg, key, "SeamSpec: locked rule check failed.\n" + "\n".join(lines) + "\n" + SUPERSEDE_HINT
    )


def _on_error(event: str, payload: dict[str, Any], store: Store | None, cfg: Config | None, exc: Exception):
    """Fail open by default. With fail_closed, Stop blocks through the same retry counter (§16.1 step
    10). PreToolUse always fails open: it is an early-warning layer, and denying every edit on a
    broken record would trap the agent. If config itself can't load, fail_closed is unknown: fail open
    (`seamspec doctor --ci` catches a broken config)."""
    msg = f"SeamSpec hook error: {exc}"
    if event == "stop" and store is not None and cfg is not None and cfg.hooks.fail_closed:
        state = SessionState.load(store, str(payload.get("session_id") or "unknown"))
        key = _start_retries(payload, state)
        return _block(state, store, cfg, key, msg + "\nAsk the user to run `seamspec status`.")
    return {"systemMessage": msg} if event == "stop" else None


# --- SessionStart: the agreements in force, before the first prompt (ADR-20261007-ac04) ---------------

SESSION_SOURCES = ("startup", "clear", "compact")  # resume/fork already carry the earlier context
SESSION_MAX_CHARS = 3000  # the summary stays small however large the ledger grows


RULES_HEADING = ("SeamSpec: rules in force in this repository. A human approved each rule, and each has a test "
                 "that must keep passing:")  # fmt: skip
DEAD_HEADING = ("SeamSpec: approaches tried before that failed (recorded, not approved); don't retry unless the "
                "reason no longer applies:")  # fmt: skip


RULES_HEADING_SHORT = ("SeamSpec: rules in force in this repository, titles only (`get_constraints` returns the full "
                       "rule). A human approved each rule, and each has a test that must keep passing:")  # fmt: skip


def _flat(text: str) -> str:
    """One line: a record's own line breaks must not turn into extra summary entries (Copilot, #41)."""
    return " ".join(text.split())


def _clip(text: str, limit: int = 100) -> str:
    text = _flat(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _area(paths: list[str]) -> str:
    """The folder a scope is about: the first path's part before any glob, e.g. src/billing/** -> src/billing."""
    first = _flat(paths[0]) if paths else ""
    plain = first.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0].rstrip("/")
    if "." in plain.rsplit("/", 1)[-1]:  # a file: its folder
        plain = plain.rsplit("/", 1)[0] if "/" in plain else ""
    return plain or "(repository root)"


def session_summary(store: Store, max_chars: int = SESSION_MAX_CHARS) -> str | None:
    """The agreements in force, built from the ledger (ADR-20261007-ac04). Detail shrinks before
    anything is dropped: every rule in full if it fits; else one line per rule (id, title, scope);
    else counts per area. No rule silently disappears. None when there is nothing to say."""
    records = store.load_all("inv") + store.load_all("de")
    locked = sorted((r for r in records if isinstance(r, Invariant) and r.status == InvStatus.LOCKED),
                    key=lambda r: r.id)  # fmt: skip
    dead = sorted((r for r in records if isinstance(r, DeadEnd) and r.status == "ACTIVE"), key=lambda r: r.id)
    waiting = sum(isinstance(r, Invariant) and r.status == InvStatus.PROPOSED for r in records)
    waiting += len(pending_supersede_ids(store))
    if not locked and not dead and not waiting:
        return None
    # Only LOCKED rules are human-approved; dead ends are recorded by agents or people, never approved.
    tail = []
    if locked:
        tail.append("If a request conflicts with one of these rules, don't change it on your own: call "
                    "`request_supersede` and ask the user first. For the full rules on a file, call "
                    "`get_constraints`.")  # fmt: skip
    if waiting:
        tail.append(f"SeamSpec: {waiting} item(s) wait for the user's review: remind them to run `seamspec review`.")

    def scope(r: Invariant | DeadEnd) -> str:
        return ", ".join(_flat(p) for p in r.scope.paths)

    full = ([RULES_HEADING] if locked else []) + [
        f"- {r.id} · {_flat(r.title)}: {_flat(r.assertion)} (scope: {scope(r)})" for r in locked
    ]  # fmt: skip
    full += ([DEAD_HEADING] if dead else []) + [
        f"- {d.id}: {_flat(d.approach)} Why it failed: {_flat(d.failure_symptom)}" for d in dead
    ]
    one_line = ([RULES_HEADING_SHORT] if locked else []) + [
        f"- {r.id} · {_flat(r.title)} (scope: {scope(r)})" for r in locked
    ]
    one_line += ([DEAD_HEADING] if dead else []) + [f"- {d.id}: {_clip(d.approach)} (scope: {scope(d)})" for d in dead]
    by_area: dict[str, list[int]] = {}
    for r in locked:
        by_area.setdefault(_area(list(r.scope.paths)), [0, 0])[0] += 1
    for d in dead:
        by_area.setdefault(_area(list(d.scope.paths)), [0, 0])[1] += 1
    counts = [f"SeamSpec: {len(locked)} rules in force (each approved by a human and backed by a test) and "
              f"{len(dead)} recorded dead ends, too many to list here. Call `get_constraints` for the files you "
              "work on; it returns every rule and dead end that applies. By area:"]  # fmt: skip
    counts += [f"- {area}: {n_r} rule(s), {n_d} dead end(s)" for area, (n_r, n_d) in sorted(by_area.items())]

    for tier in (full, one_line, counts):
        text = "\n".join(tier + tail)
        if len(text) <= max_chars:
            return text
    # Even the per-area list is too long: totals only (never silently empty).
    return "\n".join([counts[0].replace(" By area:", "")] + tail)


def session_start(payload: dict[str, Any], store: Store, cfg: Config) -> dict[str, Any] | None:
    """Context, not enforcement: runs in every mode and never runs tests."""
    if payload.get("source", "startup") not in SESSION_SOURCES:
        return None
    text = session_summary(store)
    if text is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}


HANDLERS = {"pre-tool-use": pre_tool_use, "stop": stop, "session-start": session_start}


def main(event: str, stdin: str | None = None) -> str:
    """Run one hook event and return what to print (possibly empty)."""
    handler = HANDLERS[event]
    payload: dict[str, Any] = {}
    store: Store | None = None
    cfg: Config | None = None
    try:  # reading stdin and loading the ledger happen inside the handler too
        payload = json.loads(stdin if stdin is not None else sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not a JSON object")
        try:
            root = find_root(Path(payload.get("cwd") or "."))
        except Exception:
            return ""  # not a SeamSpec project: stay silent
        store = Store(root)
        cfg = load_config(root)
        out = handler(payload, store, cfg)
    except Exception as exc:
        print(f"seamspec hook error: {exc}", file=sys.stderr)
        out = _on_error(event, payload, store, cfg, exc)
    return json.dumps(out) if out else ""
