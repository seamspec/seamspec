---
id: ADR-20261013-e8f3
title: "Cursor, VS Code and Antigravity in v0.1: rules, tools, session-start and stop hooks"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/installers/hosts.py", "seamspec/adapters/hosts.py", "seamspec/core/commands.py", "seamspec/installers/directive.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-e8f3: Cursor, VS Code and Antigravity in v0.1: rules, tools, session-start and stop hooks

## Context

The owner moved support for Cursor, VS Code (Copilot) and Google Antigravity into v0.1 (ADR-20261013-f4a8) and has all three installed. SPEC §16.2 and §16.3 designed the Cursor and VS Code adapters on 2026-10-05; Antigravity is new.

Reading the public documentation again on 2026-10-13 (clean room: docs only), all three support what SeamSpec needs at project level:

| | Rules | MCP config | Hooks | Session start → context | Stop → keep going |
|---|---|---|---|---|---|
| Cursor | `AGENTS.md`, `.cursor/rules` | `.cursor/mcp.json` | `.cursor/hooks.json` | `additional_context` | `followup_message`, capped by `loop_limit` |
| VS Code (Preview) | `AGENTS.md`, `.github/copilot-instructions.md` | `.vscode/mcp.json` | `.github/hooks/*.json` | `hookSpecificOutput.additionalContext` | `hookSpecificOutput.decision = "block"` + `reason` |
| Antigravity | `AGENTS.md`, `.agents/rules` | `.agents/mcp_config.json` | `.agents/hooks.json` | `injectSteps[].systemMessage` | `decision = "continue"` + `reason` |

What the docs don't give is each host's tool names and arguments for file edits, which SeamSpec's edit-time context and ledger protection key on (§7.2).

## Decision

1. **`seamspec init --hosts cursor,vscode,antigravity`** sets SeamSpec up for those hosts. Without the option, an interactive `init` asks for each host whose folder exists (`.cursor/`, `.vscode/`, `.agents/` or `.agent/`), and a non-interactive one only says how. Nothing is installed without a yes or the option.
2. **Project files only, merged, never overwriting:**
   - the SeamSpec protocol in **`AGENTS.md`**, which all three read: the same block as `CLAUDE.md`, worded with their command names (`/seamspec-drain`) and without SeamSpec's reviewer, which only the Claude Code plugin ships (ADR-20261013-b7d2). Lines a user writes inside it are kept (ADR-20261011-b1c8);
   - SeamSpec's **MCP server** entry, added if missing; a different `seamspec` entry is left as it is;
   - the **session-start** and **stop** hooks, added unless an entry with the same command is there; other hooks are never touched; a file that isn't valid JSON is skipped and reported;
   - **`/seamspec-<name>` commands** rendered from the same templates as the Claude Code skills, in each host's format (Cursor command, VS Code prompt file, Antigravity skill). These files are SeamSpec's and are rewritten to match its version.
3. **One adapter, `adapters/hosts.py`,** translates each host's hook input into the payload the Claude Code handlers read, runs them (the same session summary, BRAINDUMP nudge and Stop check, with the same consent and trust checks), and translates the answer back. SeamSpec keeps its own retry budget (`verify.max_stop_retries`); Cursor's `loop_limit` is set to the same number. Antigravity's Stop runs only when `fullyIdle` is true. Informational messages have no field on these hosts and are dropped. Any error: no output.
4. **Not yet:** edit-time context and ledger protection (`preToolUse` / `afterFileEdit` in §16.2–§16.3). They need each host's edit tool names, which the owner's hands-on check can read from the host's logs. Until then the commit gate and CI protect the ledger on every host, as for any MCP client.

**Alternatives considered:**
- **Level 1 only (rules, tools, commit gate), no hooks.** All three document session-start and stop hooks; without them the agent would start each session without the rules in force and finish with a broken rule unnoticed until commit.
- **Guess the edit tool names.** A wrong guess either blocks nothing or blocks the wrong thing; both are worse than waiting for the hands-on check.
- **A rules file per host** (`.cursor/rules/seamspec.mdc`, `.github/copilot-instructions.md`, `.agents/rules/seamspec.md`). One `AGENTS.md` block serves all three and is one more place a user already looks.
- **Per-host adapter modules.** The three differ only in field names; one translation table is easier to keep right.

## Limits

- **Not yet run in any of the three tools.** Everything above comes from their documentation and is covered by tests that feed each documented format through the adapter. The owner has all three installed; a short check in each is the next step.
- **VS Code's hooks are Preview** and run only in its local agent harness.
- **The hooks call `seamspec` from the PATH**; if a tool can't find it, the hook fails open (no context, no stop check) and the commit gate still applies.
- The reviewer (`/seamspec:explain`) is Claude Code only for now.

## Enforced Invariants

None new. The existing rules on consent and trust apply to the stop hooks through the shared handlers.

## Consequences

- SPEC §8 lists all four hosts, with the "session + gate" tier for the new three; §16.2, §16.3 and a new §16.3a describe what is built; §15A.4 lists the command files.
- `seamspec doctor` warns when the `AGENTS.md` block is outdated.
- `directive_known_lines.txt` also records the `AGENTS.md` wording.
