"""Hook adapters for Cursor, VS Code (Copilot) and Antigravity (SPEC §16.2–§16.4, ADR-20261013-e8f3).

Each host calls `seamspec hook <host> <event>` with its own JSON. This module translates that into
the payload the Claude Code adapter's handlers already understand, runs them (the same session-start
summary, BRAINDUMP nudge and Stop check), and translates the answer back into the host's format:

| Host | Session start: context | Stop: send the agent back with a reason |
|---|---|---|
| Cursor | `additional_context` | `followup_message` (Cursor caps repeats with `loop_limit`) |
| VS Code | `hookSpecificOutput.additionalContext` | `hookSpecificOutput.decision = "block"` + `reason` |
| (the same file, Copilot agent) | also top-level `additionalContext` | also top-level `decision` + `reason` |
| Antigravity | `injectSteps[].systemMessage` | `decision = "continue"` + `reason` |

VS Code's hook file also serves the **Copilot agent** (VS Code's Copilot sessions, the Copilot CLI):
it reads `.github/hooks/*.json` with `"version": 1`, takes VS Code's event names and payload, and
reads its own fields at the top level. The answer carries both, so either reader finds it
(ADR-20261016-2d9a).

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

# Cursor and VS Code leave a project's MCP server off until the person allows it. The agent can't tell
# them that SeamSpec's tools are off unless it is told where they are switched on (ADR-20261018-9c4d).
TOOLS_OFF = {
    "cursor": "Cursor Settings → MCP (or Tools), switch `seamspec` on",
    "vscode": "Command Palette → `MCP: List Servers` → seamspec → Start",
}


def tools_off_note(host: str) -> str | None:
    where = TOOLS_OFF.get(host)
    if where is None:
        return None
    return (f"SeamSpec: if SeamSpec's tools (get_constraints, propose_invariant, …) aren't available in this chat, "
            f"tell the user once that its server is off and how to turn it on ({where}); until then use the "
            "matching `seamspec` commands in the shell.")  # fmt: skip


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
        session = payload.get("session_id") or payload.get("sessionId") or payload.get("conversation_id")
        if host == "vscode":
            again = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
        else:
            again = int(payload.get("loop_count") or 0) > 0
    out: dict[str, Any] = {"cwd": cwd, "session_id": f"{host}-{session or 'unknown'}"}
    if event == "session-start":
        out["source"] = "startup"  # these hosts start fresh sessions only (VS Code reports "new")
    else:
        out["stop_hook_active"] = again
    return out


def _from_claude(host: str, event: str, answer: dict[str, Any]) -> dict[str, Any] | None:
    if event == "session-start":
        text = "\n".join(
            t for t in (answer.get("hookSpecificOutput", {}).get("additionalContext"), tools_off_note(host)) if t
        )
        if not text:
            return None
        if host == "cursor":
            return {"additional_context": text}
        if host == "vscode":  # VS Code reads hookSpecificOutput; the Copilot agent, the top level
            return {"additionalContext": text,
                    "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}  # fmt: skip
        return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}
    if answer.get("decision") != "block":
        return None  # allowed: an informational message has no place in these hosts' stop output
    reason = str(answer.get("reason") or "SeamSpec: a locked rule failed.")
    if host == "cursor":
        return {"followup_message": reason}
    if host == "vscode":
        return {"decision": "block", "reason": reason,
                "hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": reason}}  # fmt: skip
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
        if not raw and not (event == "session-start" and tools_off_note(host)):
            return ""
        out = _from_claude(host, event, json.loads(raw) if raw else {})
    except Exception as exc:  # noqa: BLE001 - a hook must never break the host
        print(f"seamspec hook error: {exc}", file=sys.stderr)
        return ""
    return json.dumps(out) if out else ""
