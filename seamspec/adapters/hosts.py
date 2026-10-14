"""Hook adapters for Cursor, VS Code (Copilot) and Antigravity (SPEC §16.2–§16.4, ADR-20261013-e8f3).

Each host calls `seamspec hook <host> <event>` with its own JSON. This module translates that into
the payload the Claude Code adapter's handlers already understand, runs them (the same session-start
summary, BRAINDUMP nudge and Stop check), and translates the answer back into the host's format:

| Host | Session start: context | Stop: send the agent back with a reason |
|---|---|---|
| Cursor | `additional_context` | `followup_message` (Cursor caps repeats with `loop_limit`) |
| VS Code | `hookSpecificOutput.additionalContext` | `hookSpecificOutput.decision = "block"` + `reason` |
| Antigravity | `injectSteps[].systemMessage` | `decision = "continue"` + `reason` |

The retry budget is SeamSpec's own (`verify.max_stop_retries`), as in Claude Code: after that many
blocks the agent may stop, and pre-commit and CI still refuse the change. Messages that only inform
(no block) have no field on these hosts and are dropped. Any error: no output (fail open).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import claude

EVENTS = ("session-start", "stop")


def _to_claude(host: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The host's hook input, as the Claude Code handlers read it."""
    if host == "antigravity":
        roots = payload.get("workspacePaths") or []
        cwd = roots[0] if roots else os.getcwd()
        session = payload.get("conversationId")
        # Antigravity says nothing about whether our own block caused this stop, so the budget is kept
        # until a green check resets it (never reset by a new stop alone).
        again = True
    else:
        cwd = payload.get("cwd") or (payload.get("workspace_roots") or [None])[0] or os.getcwd()
        session = payload.get("session_id") or payload.get("conversation_id")
        again = bool(payload.get("stop_hook_active")) if host == "vscode" else int(payload.get("loop_count") or 0) > 0
    out: dict[str, Any] = {"cwd": cwd, "session_id": f"{host}-{session or 'unknown'}"}
    if event == "session-start":
        out["source"] = "startup"  # these hosts start fresh sessions only (VS Code reports "new")
    else:
        out["stop_hook_active"] = again
    return out


def _from_claude(host: str, event: str, answer: dict[str, Any]) -> dict[str, Any] | None:
    if event == "session-start":
        text = answer.get("hookSpecificOutput", {}).get("additionalContext")
        if not text:
            return None
        if host == "cursor":
            return {"additional_context": text}
        if host == "vscode":
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
        return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}
    if answer.get("decision") != "block":
        return None  # allowed: an informational message has no place in these hosts' stop output
    reason = str(answer.get("reason") or "SeamSpec: a locked rule failed.")
    if host == "cursor":
        return {"followup_message": reason}
    if host == "vscode":
        return {"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": reason}}
    return {"decision": "continue", "reason": reason}


def main(host: str, event: str, stdin: str | None = None) -> str:
    """Run one hook event for a host; returns what to print (possibly empty)."""
    try:
        payload = json.loads(stdin if stdin is not None else sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return ""
        if host == "antigravity" and event == "stop" and payload.get("fullyIdle") is False:
            return ""  # background work still running: check when the agent is really done
        raw = claude.main(event, json.dumps(_to_claude(host, event, payload)))
        if not raw:
            return ""
        out = _from_claude(host, event, json.loads(raw))
    except Exception as exc:  # noqa: BLE001 - a hook must never break the host
        print(f"seamspec hook error: {exc}", file=sys.stderr)
        return ""
    return json.dumps(out) if out else ""
