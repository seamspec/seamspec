---
id: ADR-20261018-9c4d
title: "Cursor gets the reviewer; the agent says when SeamSpec's tools are off; a setup guide per editor"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-18
scopes: ["seamspec/core/commands.py", "seamspec/installers/directive.py", "seamspec/adapters/hosts.py", "docs/editors.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261018-9c4d: Cursor reviewer, "tools off" note, setup guide

## Context

After the hands-on tests of all four tools, the owner asked three questions, which led to three decisions.

1. **"So there is no seamspec-explain in Cursor and we can't build it?"** ADR-20261015-4f7b left Cursor out because its read-only switch also blocks MCP tools. But Antigravity's reviewer already works without SeamSpec's tool: it reads the ledger from disk. The same design fits Cursor's read-only subagents (`.cursor/agents/<name>.md`, `readonly: true`, which blocks file edits and state-changing shell commands; started by the main agent or with `/name`, per cursor.com/docs/context/subagents).
2. **"How would users know to enable the server?"** Cursor and VS Code leave a project's MCP server off until the person allows it. In the Cursor test, the agent quietly used SeamSpec's shell commands instead. The rules held, but nobody told the owner that the tools were off.
3. **"Why were Claude Code and Antigravity straightforward?"** Claude Code's plugin install is the permission, and Antigravity runs a project's hooks and servers without asking. Cursor and VS Code ask first, deliberately. Users need that written down in one place.

## Decision

1. **Cursor gets the reviewer:** `.cursor/agents/seamspec-reviewer.md` with `readonly: true` and `model: inherit`, from the same prompt. `/seamspec-explain` is a command telling the working agent to use the subagent and relay its answer unchanged, or the user types `/seamspec-reviewer`. `AGENTS.md` now offers `/seamspec-explain` to all three tools.
2. **The agent says when the tools are off.** Cursor's and VS Code's session-start text always ends with: *"if SeamSpec's tools … aren't available in this chat, tell the user once that its server is off and how to turn it on (<where>); until then use the matching `seamspec` commands in the shell."* It is sent even with an empty ledger. A hook can't see whether the server is on, so the agent, which can, decides.
3. **`docs/editors.md`**, a user-facing guide: what `init` writes for each tool, the one-time step each needs (the two Copilot Business policies included), what works, what still doesn't, and why the rules hold even without the tools.

**Alternatives considered:**
- **Detecting in a hook whether the server is on:** neither tool tells hooks that. Reading their settings files would be fragile and touch files that aren't the project's.
- **Turning the servers on for the person:** that would get around the editors' consent step.

## Enforced Invariants

None yet.

## Consequences

- All four tools have `/seamspec-explain`. Cursor's reviewer still needs a hands-on try, since its forum reports bugs with read-only subagents.
- The start-of-chat text in Cursor and VS Code is one line longer, even when the tools are on.
- The README will link `docs/editors.md`.
