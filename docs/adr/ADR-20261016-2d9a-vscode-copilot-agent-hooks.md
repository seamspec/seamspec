---
id: ADR-20261016-2d9a
title: "VS Code hands-on: one hook file for VS Code's Local and Copilot agents, and setup notes"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-16
scopes: ["seamspec/installers/hosts.py", "seamspec/adapters/hosts.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261016-2d9a: VS Code hands-on fixes

## Context

The owner's VS Code hands-on test (2026-10-16, in `~/Documents/bdtest`) found three things.

1. **Two org policies hid SeamSpec.** The owner's Copilot is a Copilot Business seat from the `seamspec` organization. Its policies **"Editor preview features"** and **"MCP servers in Copilot"** were off, which is the default. VS Code showed hooks as "Managed by organization" and showed no MCP server. The owner turned both on.
2. **The hooks ran in only one of VS Code's two agents.**
   - VS Code's hooks log showed SeamSpec's `SessionStart` running once, in a chat on the **Local** agent, and its summary reaching the chat.
   - Later chats ran in the **Copilot** agent (VS Code's "Agent Host", the same agent as the Copilot CLI; its tools showed as `view`, `bash`, `rg`, `seamspec-get_constraints`). There, with `cart.py` broken by hand, the agent finished a turn and no `Stop` hook ran.
   - GitHub's hooks reference says the Copilot agent loads `.github/hooks/*.json` as well, but rejects a file whose `version` is bad (and, by its wording, missing). It takes PascalCase event names with the "VS Code-compatible payload format", and reads its replies at the top level (`additionalContext`; `decision` + `reason`).
3. **What went well:**
   - the tools worked in both agents;
   - the agent declined a duplicate rule (it was already locked) and declined a change that broke locked rules;
   - `seamspec verify` named each failing rule with its failing line;
   - the commit check passed a clean tree.

## Decision

1. **One hook file for both agents.** `.github/hooks/seamspec.json` gets `"version": 1`, and each entry gets `timeoutSec` next to `timeout`. A rerun of `init` upgrades an older file, carrying over a hand-tuned `timeout`.
2. **The `vscode` adapter answers in both shapes:**
   - top-level `additionalContext`, or `decision: "block"` + `reason`, for the Copilot agent;
   - `hookSpecificOutput`, for the Local agent.
   - It reads `sessionId` and `stopHookActive` as well as `session_id` and `stop_hook_active`.
   - Because the Copilot CLI reads the same repository file, the same hooks should reach it, with no change of its own.
3. **`init --hosts vscode` prints what only a person can do:**
   - start the server once (`MCP: List Servers` → seamspec → Start);
   - on Copilot Business or Enterprise, have an org admin enable the two policies.

   SeamSpec doesn't change editor settings or org policies, and doesn't work around trust prompts.
4. **The Copilot agent's `preToolUse` waits.** Its edit tools weren't seen in the logs, so edit-time context and ledger protection follow a hands-on run in which the agent edits a file.

**Alternatives considered:**
- **A second hook file in the Copilot format** (`sessionStart` / `agentStop`, `bash`): two files that must stay in step. The Copilot agent's documented VS Code compatibility makes one file enough.
- **Writing `chat.useHooks` or `chat.mcp.autostart` into `.vscode/settings.json`:** `chat.useHooks` is on by default (the org policy was what blocked it), and `chat.mcp.autostart` is experimental with undocumented values. Not worth a settings change made on the person's behalf.

## Enforced Invariants

None yet.

## Consequences

- **Not yet confirmed hands-on in the Copilot agent:** the owner's next step is a Copilot-session stop check after rerunning `seamspec init --hosts vscode`.
- Teams on Copilot Business or Enterprise need an admin step before SeamSpec's hooks and tools work in VS Code. The README must say so.
- **GitHub's cloud agent** also reads `.github/hooks/*.json`, but only `bash` (or the `command` fallback) in `/workspace`, and SeamSpec would have to be installed in its environment. Not covered in v0.1.
