---
id: ADR-20261017-1f5c
title: "Cursor hands-on: hooks work as built; init says to switch the server on"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-17
scopes: ["seamspec/installers/hosts.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261017-1f5c: Cursor hands-on

## Context

The owner tested SeamSpec in Cursor 3.21 on `~/Documents/bdtest` (9 locked rules). This was the last of the four tools to be tried hands-on. Cursor's hook log and agent transcript showed the following.

- **Hooks ran with no setup:**
  - `sessionStart` returned the rules summary;
  - `stop` ran after every turn and stayed silent while every rule passed;
  - with `total()` broken by hand, the agent finished an unrelated task, got SeamSpec's failure report as Cursor's automatic follow-up ("Attempt 1 of 3"), fixed exactly the broken line, didn't request a supersede, and left the rule tests untouched.
- **The server stayed off until switched on.** Cursor started SeamSpec's MCP server in the project folder, so the Antigravity fix wasn't needed, but it left the project's server **off** until the owner switched it on in Cursor's settings. Until then, the agent used the shell fallback that protocol rule 5 (ADR-20261014-6c2d) prescribes: `seamspec context cart.py`. Cursor's chat showed only the end of that output, but the agent read all of it.
- **Tool names in the transcript:** `StrReplace` (edit), `Read`, `Shell`, and MCP calls through `CallDynamicTool`.

## Decision

1. `seamspec init --hosts cursor` prints: *"Cursor: switch SeamSpec's server on once (Cursor Settings → MCP / Tools, or Cmd+Shift+P → `MCP`): Cursor leaves a project's servers off until you do. Its hooks need nothing."*
2. Record the results in SPEC §16.3, along with the tool names seen, as the starting point for Cursor's `pre-tool-use` hook. The hook itself waits until the names its hooks receive are confirmed.

**Alternatives considered:**
- **Turning the server on for the person** (writing Cursor's own settings): it's Cursor's consent step for running a command, and SeamSpec mustn't work around it.

## Enforced Invariants

None yet.

## Consequences

- All four tools have now been tried hands-on. The end-of-task check has blocked a broken rule in Claude Code, Antigravity, VS Code (Copilot agent) and Cursor.
- Still open for Cursor: the reviewer (its read-only mode blocks MCP tools) and edit-time context / ledger protection.
