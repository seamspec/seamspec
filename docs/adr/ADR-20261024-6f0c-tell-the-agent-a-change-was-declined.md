---
id: ADR-20261024-6f0c
title: Tell the agent when a person declined a supersede request
status: ACCEPTED
date: 2026-10-24
scopes: ["seamspec/core/requests.py", "seamspec/adapters/claude.py", "seamspec/core/context.py", "seamspec/review.py", "seamspec/chat_review.py", "docs/SPEC.md", "docs/editors.md"]
invariants: []
supersedes: null
superseded_by: null
---

# Tell the agent when a person declined a supersede request

## Context

In the release rehearsal (2026-10-24) the owner asked VS Code's Copilot agent for a change that broke a locked rule. The agent made the change, proposed a replacement rule and filed a supersede request, as the protocol allows (§11.2). The owner declined it in `seamspec review`.

SeamSpec then deleted the request and kept nothing. On its next stop, the agent got the same block as before: *"Fix the regression. If this behavior change is intentional, call request_supersede…"*. From its own chat history it still believed its request was pending. Three blocks later (`max_stop_retries`), it was still telling the owner that the request "is already created and pending" and recommending approval, instead of restoring the rule. The commit check held throughout, so nothing broken was committed, but the agent never learned that a person had already decided.

Claude Code took the same route as Copilot (change, replacement, request) and explained it well. So agents do use the "change, then ask" path, and the decline must reach them.

## Decision

1. **Remember a decline.** Declining a supersede request, in `seamspec review` or in a chat review, drops the request as before and keeps a note in `.seamspec/.local/declined/<inv_id>.json`. The note holds the date, the person's reason (a chat review asks for one; the terminal review doesn't) and what the agent had asked. It is machine-local, like requests.
2. **Tell the agent, wherever it looks**, while the rule is still `LOCKED`: *"A person declined the request to retire inv_… (title) on <date>. Their reason: … Keep the behavior it protects: restore it if your change broke it, and don't ask to change it again unless the user asks for that change."*
   - **Stop hook:** added to the block. When every failing rule was declined, the last line becomes *"Fix the regression: a person already decided to keep these rules."* instead of the supersede advice.
   - **`get_constraints` / `seamspec context`:** for the files the rule covers (`declined`).
   - **Session start:** under *"SeamSpec: changes a person declined; the rules stay in force:"*, so a new chat doesn't ask again.
   This is shared code, so it applies to Claude Code, Cursor, VS Code and Antigravity alike.
3. **A new request replaces the note.** If the user asks for the change again, the agent's new request is pending again and the Stop hook's supersede escape applies as before.

**Alternatives considered:**
- *Make agents ask before changing the code.* It would avoid the undo, but the "change, then ask" path lets the reviewer see working code and a passing replacement, and the commit check blocks it either way. It stays allowed; the owner can still decide otherwise.
- *Keep the decline in the ledger (committed).* Declines are a conversation between one person and their agent; teammates' agents learn from the rule itself, which is still locked. Machine-local, like requests.

**Also from the rehearsal:** VS Code can hold an agent's edits in the editor until the user clicks Keep. SeamSpec's checks read the files on disk, so the agent's change wasn't there yet. `docs/editors.md` now says so. That is VS Code behaviour, not something SeamSpec should work around.

## Enforced Invariants

None. Covered by `tests/test_claude_adapter.py` (request, decline, then the stop block, session start, `get_constraints`, and asking again), `tests/test_review.py` and `tests/test_chat_review.py` (both decline paths keep the note).

## Consequences

- After a decline, the agent is told to restore the rule rather than asking again.
- A declined rule keeps its note until someone asks again or the rule is retired; it is one line per rule in the session-start text.
