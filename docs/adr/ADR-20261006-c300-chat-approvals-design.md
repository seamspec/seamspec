---
id: ADR-20261006-c300
title: Approvals in chat through an MCP form dialog, with hook guards (design)
status: PROPOSED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-06
scopes: ["seamspec/mcp_server.py", "seamspec/review.py", "seamspec/core/lifecycle.py", "seamspec-plugin/hooks/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261006-c300: Approvals in chat through an MCP form dialog, with hook guards (design)

> **Status: PROPOSED.** This is a design for the owner to decide on. Nothing is built yet. The questions at the end need answers, and the verification runs need the owner's OK, before implementation starts.

## Context

Hands-on finding #8: when the agent proposes a rule or asks to supersede one, the human has to leave the chat, open a terminal and run `seamspec review`. That round trip is the biggest remaining setup-and-use friction. It matters most in the Claude Code desktop app and IDE chat, where there may be no terminal open at all.

**What "human only" means today.** `approve`, `reject`, `supersede` and `retire-dead-end` require an interactive terminal (`require_interactive()`). The code and SPEC §19.8 describe this as *a speed bump, not a security boundary*: an agent with an unrestricted shell can fake a terminal (e.g. with `script`). The real protections are:
- the approval journal, checked at Stop and pre-commit;
- approvals land in committed JSON that a human reviews in the PR;
- CODEOWNERS on `.seamspec/` (strict mode) and the CI provenance check (§11.1, §16.5).

Any chat channel must be **no weaker than this in practice**, and must stay **visible in review**.

**Facts checked against the current Claude Code docs (hooks and MCP reference, 2026-10-06):**

1. **MCP elicitation.** An MCP server can ask the human for input mid-tool-call. Claude Code shows a **form dialog** (fields defined by the server) or a **URL dialog** (asks to open a link). No setup is needed. The model does not answer the dialog. Claude Code declares both modes on protocol revision 2026-07-28. Our SDK (MCP Python SDK 2.x) has `ctx.elicit(message, schema)` and `ctx.elicit_url(...)`.
2. **The `Elicitation` hook can answer a dialog itself,** without showing it (`action: accept` plus field values). Its matcher is the MCP server name. **The `ElicitationResult` hook can rewrite the human's answer** before it reaches the server (e.g. turn a decline into an accept).
3. **Hook edits in settings files apply mid-session** ("picked up automatically by the file watcher"). An agent that can write `.claude/settings.local.json` could add such a hook during a session.
4. **A `ConfigChange` hook can block** a change to user, project or local settings from applying to the running session. It can't block managed-policy changes.
5. **`UserPromptSubmit` is not "only what the human typed".** It also fires for scheduled tasks, background subagents reporting back, and messages from other sessions. Text the human didn't type can arrive there.
6. In `-p` (headless) sessions there is no one to show a dialog to; the behavior is not documented (verification run 3).

## Options considered

| | Option | How the human approves | Verdict |
|---|---|---|---|
| **A** | **Form dialog (MCP elicitation)** | The agent calls a new MCP tool `open_review`. SeamSpec shows each pending item in a Claude Code dialog; the human picks approve / reject / skip. | **Recommended for v0.1.** Smallest change. It's the MCP-standard "server asks the human" channel, so it carries over to other hosts in v0.2. Needs the hook guards below. |
| B | Local review page (URL elicitation) | The dialog offers a link to a page served by `seamspec` on `127.0.0.1` with a one-time token. The human reviews and clicks there. | **Later (v0.2, "dashboard").** Best viewing: full test with highlighting, red-green result, and the diff for replaced proposals (finding #7). Several times the code (HTTP server, HTML, token lifecycle). Any process running as the user can still drive it, so it's no stronger than A. |
| C | Typed command in chat (`UserPromptSubmit` hook) | The human types `seamspec approve inv_…`; a hook intercepts it before the model sees it. | **Rejected.** Fact 5: that hook also receives text the human didn't type (other sessions, background subagents, scheduled tasks), so an agent could "type" an approval. |
| D | Status quo plus pointers | The agent tells the human to run `seamspec review` in the terminal. | Stays as the **fallback**: headless sessions, hosts without elicitation, runner-config changes, and whenever a guard trips. |

## Proposed decision (option A)

**Flow.**
1. The human says "let me review" (or the `/seamspec:lock` and supersede skills offer it after proposing).
2. The agent calls `open_review(ids?)`. The agent passes only ids; it never supplies the text shown.
3. For each item, the server runs the guards. It runs the red-green check if execution is permitted; otherwise the dialog says "red-green not run".
4. The server opens **one form dialog per item**. The tool result tells the agent only the outcomes (e.g. "inv_… approved", "inv_… skipped"). The agent never sees or answers the dialog.

**Dialog content.** Rendered by SeamSpec from the ledger, never written by the agent:
- the rule, scope and runner;
- the **full test code**;
- the red-green result;
- the quoted origin;
- for a replaced proposal, what changed (finding #7);
- for a supersede request, the old and the new rule.

**Form fields.**
- `decision`: approve / reject / skip, **no default**;
- `reason`: text, required for reject;
- `also_dead_end`: checkbox, on reject;
- header line: *"From SeamSpec, not the agent. The agent can't answer this dialog."*

**In scope for chat.** New proposals, supersede requests (the case that sent the owner to the terminal), and dead-end keep / wrong.
**Terminal only.** Runner-config changes, because they change *what executes*. While runner config is unconfirmed, approvals are blocked, as today (§11.4).

**Guards.**

1. **No hook may intercept our dialogs.**
   - **Before each dialog**, the server reads every hook source it can see:
     - `~/.claude/settings.json`;
     - `.claude/settings.json` and `.claude/settings.local.json`;
     - managed settings;
     - the `hooks/hooks.json` of every enabled plugin.
   - If any `Elicitation` or `ElicitationResult` hook could match SeamSpec's server name, it **refuses chat approvals**. It names the hook and points to `seamspec review`.
   - **During the session**, the plugin adds a `ConfigChange` hook. It blocks a user, project or local settings change that would add such a hook, and records the attempt in the journal.
   - This is best effort: it can't see hooks configured in places it doesn't know about, or changes made before the session starts. Those are covered by provenance (guard 3).
2. **Only when a human can answer.**
   - The client must declare form elicitation.
   - In headless sessions, or on any `cancel`, nothing changes and the tool falls back to option D.
   - At most one open dialog. An item declined or cancelled isn't offered again in the same session unless the human asks, so the agent can't spam dialogs until one gets clicked through.
3. **Provenance is committed and visible in review.**
   - Approval records get `approved_via: "terminal" | "chat"`, a schema addition; old records read as `"terminal"`.
   - The journal records the channel plus the host's client name and version.
   - `seamspec status`, `review` and the CI provenance check show it, so a PR reviewer sees *"approved in chat"* in the diff.
4. **Strict mode: off by default.** New config key `[review] chat_approvals = true | false`. Default `true` in advisory and enforced, `false` in strict. Explicit config wins, like `trust_level` (§26 #8).
5. **Same rules as the terminal path.** Approval still refuses changed runner config (`confirm_config`), still requires the harness and assertion hashes, and still writes the journal entry.

**Residual risk (stated in SPEC §12.4.8 and §20):** an agent with an unrestricted shell can still bypass this, exactly as it can bypass the terminal check today. It could, for example, write a hook before a session starts, or drive the user's own processes. SeamSpec makes the honest path easy and the dishonest path visible; it doesn't claim to stop a determined agent with a shell.

## Verification before implementing (needs the owner's OK)

| # | What | How | Cost |
|---|---|---|---|
| 1 | The SDK's `ctx.elicit` round trip, accept / decline / cancel | In-process test with `mcp.Client` and an elicitation callback | free |
| 2 | How Claude Code renders a long message with code in a form dialog, **in the CLI and in the desktop app** | A throwaway MCP tool in a scratch repo; the owner clicks through once in each | owner's time, ≈ $0.02 |
| 3 | What happens in `claude -p` (expected: cancel or decline, then fallback) | One headless Haiku session | ≈ $0.03 |
| 4 | Guard 1 works: an `Elicitation` hook from settings and from another plugin matches `plugin:seamspec:seamspec`; a `ConfigChange` hook blocks an agent's `Write` to `.claude/settings.local.json` | Two short sessions in a throwaway config (`CLAUDE_CONFIG_DIR`) | ≈ $0.05–0.10 |

Total ≈ $0.10–0.20 on Haiku, under the same rules as the earlier sessions: the owner approves first, and runs happen in throwaway repos and configs.

## Questions for the owner

1. Option A now, B (local review page) in v0.2: agreed?
2. In scope for chat: proposals, supersede requests and dead ends; runner config stays terminal-only. Agreed?
3. Strict mode: chat approvals off by default. Agreed?
4. OK to run verification 2–4 (≈ $0.20), with you clicking the dialog in run 2?

## Enforced Invariants
To be proposed when built: "the agent never supplies dialog text", "chat approval refuses when an Elicitation hook could match", "approved_via is recorded".

## Consequences (if accepted)
* Approvals happen without leaving the chat, in the desktop app, IDE chat and CLI alike.
* Schema v1 gains an optional `approved_via`; `config.toml` gains `[review] chat_approvals`. Both are additive.
* SPEC §7.3, §9, §11.1, §11.4, §14.1, §16.1, §19 and §20 are updated in the implementation PR.
