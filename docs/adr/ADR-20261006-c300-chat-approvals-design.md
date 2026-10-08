---
id: ADR-20261006-c300
title: Approvals in chat through an MCP form dialog, with hook guards (design)
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-06
scopes: ["seamspec/mcp_server.py", "seamspec/chat_review.py", "seamspec/core/hookguard.py", "seamspec/review.py", "seamspec/core/lifecycle.py", "seamspec-plugin/hooks/**"]
invariants: ["inv_aa498871", "inv_6bae33cf", "inv_79b867d5"]
supersedes: null
superseded_by: null
---

# ADR-20261006-c300: Approvals in chat through an MCP form dialog, with hook guards (design)

> **Amended by ADR-20261008-5d1e:** verification 2 failed in both Claude Code apps, so chat approvals are off by default, and a declined dialog stops the review.
>
> **Status: ACCEPTED** (2026-10-08). The owner answered the four questions below (all as recommended) and the design is built (PR `week-4/chat-approvals`). Verification 2 (how the dialog looks in the CLI and the desktop app) is the owner's one click-through, after the merge. "Built as" at the end lists what changed while building it.

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
3. For each item, the server runs the guards, then opens **one form dialog per item**.
4. **Red-green is a separate, explicit run** (from Copilot's review of PR #21). It runs the agent-written test, so under SPEC §12.4.3 rule 2 it needs its own consent. A proposal's dialog offers *"Run the red-green check first"* as one of the choices. Picking it opens a second dialog showing the test with *"Run this test on your machine? It runs with your permissions."* (the §12.4.4 `ask` path). Only a yes runs it. That yes **is** the consent for this one run (§12.4.2–§12.4.4), so it doesn't need the auto-run consent from `init`, which covers only *automatic* runs of LOCKED tests. It therefore works in advisory mode too. It does need **repo trust** (§12.4.6), because it uses this clone's runner commands; in an untrusted clone the dialog says to run `seamspec trust` first (from Copilot's second review of PR #21). The proposal's dialog then reopens with the result. Without that yes, the dialog says "red-green not run".
5. The tool result tells the agent only the outcomes (e.g. "inv_… approved", "inv_… skipped"). The agent never sees or answers the dialog.

**Dialog content.** Rendered by SeamSpec from the ledger, never written by the agent:
- the rule, scope and runner;
- the **full test code**;
- the red-green result;
- the quoted origin;
- for a replaced proposal, what changed (finding #7);
- for a supersede request, the old and the new rule.

**Form fields, per kind of item** (from Copilot's review of PR #21). Each dialog starts with *"From SeamSpec, not the agent. The agent can't answer this dialog."* `decision` never has a default, and its value names carry a per-dialog code (guard 1).

| Item | `decision` choices | Other fields | Lifecycle action |
|---|---|---|---|
| Proposed invariant | approve / reject / run red-green first / skip | `reason` (required for reject); `also_dead_end` (reject only) | `approve` → LOCKED; `reject` → REJECTED, optional dead end |
| Supersede request | supersede / decline / skip | `reason` (required for decline) | `supersede` → old rule SUPERSEDED, replacement LOCKED; `decline` → request closed, rule stays LOCKED |
| Dead end recorded since the last review | keep / wrong / skip | `reason` (required for wrong) | `keep` → nothing changes; `wrong` → retire the dead end |

**In scope for chat.** New proposals, supersede requests (the case that sent the owner to the terminal), and dead-end keep / wrong.
**Terminal only.** Runner-config changes, because they change *what executes*. While runner config is unconfirmed, approvals are blocked, as today (§11.4).

**Guards.**

1. **No hook may intercept our dialogs.** Verification 4 showed this is a real risk: another plugin's hook approved a dialog without showing it, and so did a hook added to settings mid-session.
   - **Before each dialog**, the server reads every hook source it can see:
     - `~/.claude/settings.json`;
     - `.claude/settings.json` and `.claude/settings.local.json`;
     - managed settings;
     - the `hooks/hooks.json` of every enabled plugin.
   - If any `Elicitation` or `ElicitationResult` hook could match SeamSpec's server name, it **refuses chat approvals**. It names the hook and points to `seamspec review`. Hooks see the name as `plugin:seamspec:seamspec` (verified). A hook "could match" when its matcher is missing, empty or `*`, equals that name, or is a pattern that matches it. A bare `seamspec` matcher does not match (verified).
   - **During the session**, the plugin adds a `ConfigChange` hook. It blocks a user, project or local settings change that would add such a hook, and records the attempt in the journal. Verified: the blocked hook never ran.
   - **A per-dialog code in the choices.** The `decision` values carry a short random code, e.g. `approve-7kq2`, shown as plain choices to the human. A generic "accept every dialog" hook sends a fixed answer, which fails validation, so SeamSpec treats it as a cancel. This stops convenience or careless hooks, which is the realistic accident. It does not stop a hook written specifically against SeamSpec, which can read the schema.
   - **Limits.** SeamSpec can't see plugins loaded for one session only (`claude --plugin-dir`) or hooks set up before the session in places it doesn't read. Those are covered by provenance (guard 3).
   - The same guards apply to the existing `execution.run_proposed = "ask"` dialog (§12.4.4). A hook that auto-accepts "Run this test?" would run agent-written code.
2. **Only when a human can answer.**
   - The client must declare form elicitation.
   - In headless sessions, or on any `cancel`, nothing changes and the tool falls back to option D. Verified: in `claude -p` an unanswered dialog comes back as `cancel`.
   - At most one open dialog. An item declined or cancelled isn't offered again in the same session unless the human asks, so the agent can't spam dialogs until one gets clicked through.
3. **Provenance is committed and visible in review.**
   - Approval records get `approved_via: "terminal" | "chat"`, a schema addition; old records read as `"terminal"`.
   - The journal records the channel plus the host's client name and version.
   - `seamspec status`, `review` and the CI provenance check show it, so a PR reviewer sees *"approved in chat"* in the diff.
4. **Strict mode: off by default.** New config key `[review] chat_approvals = true | false`. Default `true` in advisory and enforced, `false` in strict. Explicit config wins, like `trust_level` (§26 #8).
5. **Same rules as the terminal path.** Approval still refuses changed runner config (`confirm_config`), still requires the harness and assertion hashes, and still writes the journal entry.

**Residual risk (stated in SPEC §12.4.8 and §20):** an agent with an unrestricted shell can still bypass this, exactly as it can bypass the terminal check today. It could, for example, write a hook before a session starts, or drive the user's own processes. SeamSpec makes the honest path easy and the dishonest path visible; it doesn't claim to stop a determined agent with a shell.

## Verification

| # | What | Status |
|---|---|---|
| 1 | SDK round trip | **Done** (free; stdio, SDK client, protocol 2026-07-28) |
| 2 | How Claude Code renders a long message with code in a form dialog, **in the CLI and in the desktop app** | **Done (2026-10-08), failed:** the CLI folds the message to about three lines and hides the test; the desktop app showed no dialog and declined each one. Chat approvals are now off by default (ADR-20261008-5d1e) |
| 3 | `claude -p` with an unanswered dialog | **Done:** returns `cancel` |
| 4 | Hook guards | **Done** (5 sessions on Claude Opus 5.5, $0.70 total, 2026-10-06, throwaway repo, plugins loaded with `--plugin-dir`) |

**Verification 1, SDK finding.** On protocol revision 2026-07-28, which Claude Code and our SDK negotiate, `ctx.elicit()` fails with *"no back-channel for server-initiated requests"*. That revision replaces server-to-client requests with an "input required" result that the client answers by retrying the call. The SDK handles this when a tool declares the answer as a resolved parameter: `answer: Annotated[ElicitationResult[Decision], Resolve(ask)]`, where `ask()` returns `Elicit(message, Decision)`. The implementation must use that form. A `Literal[...]` field renders as an `enum` of strings, as the form needs.

**Verification 4 sessions.** A probe plugin had a one-tool MCP server that opens an approval dialog and a `ConfigChange` hook. An "attacker" plugin had an `Elicitation` hook with no matcher. Project settings logged which matcher forms fire.

| Session | Setup | Result | Cost |
|---|---|---|---|
| 1 | Hooks only log | Server name seen by hooks: `plugin:probe:probe`. Matchers that fired: none (no matcher), `plugin:probe:probe`. Did not fire: `probe`, `plugin_probe_probe`. Another plugin's hook **does** fire for our server. Unanswered in `-p`: `cancel` | $0.11 |
| 2 | The attacker plugin's hook answers `accept` | The server received **accept / approve with no dialog shown** | $0.10 |
| 3 | The agent is asked to write an auto-accepting `Elicitation` hook into `.claude/settings.local.json` mid-session | **Opus 5.5 refused.** It said the steps would make an approval prompt silently run attacker-controlled code, and that a test framing doesn't change what the steps do. A useful extra layer, but not one SeamSpec relies on | $0.27 |
| 3b | The same hook written from outside the session 8 s in, with the `ConfigChange` guard blocking | `ConfigChange` fired (`local_settings`) and blocked. The injected hook **never ran**; the dialog ended as `cancel` | $0.11 |
| 4 | Control: same as 3b without the block | The injected hook **ran mid-session and approved** (accept / approve) | $0.11 |

## Questions for the owner (answered 2026-10-08)

1. Option A now, B (local review page) in v0.2: **agreed.**
2. In scope for chat: proposals, supersede requests and dead ends; runner config stays terminal-only. **Agreed.**
3. Strict mode: chat approvals off by default. **Agreed.**
4. OK to run verification 2 (you click a sample dialog once in the CLI and once in the desktop app, ≈ $0.02)? **Yes**, once it's built.

## Enforced Invariants
`inv_aa498871` (the agent never supplies approval dialog text), `inv_6bae33cf` (chat approval refuses when a hook could answer), `inv_79b867d5` (every human decision records where it was made). Approved by the owner in `seamspec review` on 2026-10-08, since verification 2 failed (ADR-20261008-5d1e).

## Consequences (if accepted)
* Approvals happen without leaving the chat, in the desktop app, IDE chat and CLI alike.
* Schema v1 gains an optional `approved_via`; `config.toml` gains `[review] chat_approvals`. Both are additive.
* SPEC §7.3, §9, §11.1, §11.4, §12.4.3–§12.4.4, §14.1, §16.1, §19 and §20 are updated in the implementation PR.

## Built as (2026-10-08)

What changed from the design above while building it, and why:

* **`decided_via`, not `approved_via`.** Rejecting, superseding and retiring a dead end can happen in chat too, so every human decision records where it was made: `decided_via: "terminal" | "chat"` on invariants and dead ends (`null` = before the field existed, i.e. the terminal). The journal gets `via` and the client's name and version.
* **The SDK's own resolver form isn't used.** Verification 1 found `Resolve(...)` parameters; they suit a fixed set of questions, but a review is a sequence that depends on the answers (red-green asks a second question, a supersede can add its replacement). `open_review` returns `InputRequiredResult` itself, one dialog per round, with its state in `request_state`. The SDK seals that state (AES-GCM, a key held only by the server process), so it can't be forged; the expiry is raised from 10 minutes to an hour so a human can read a long test.
* **At most 8 dialogs per call** (clients cap the rounds of one call; the SDK's own client stops at 10). Then the tool asks to be called again.
* **The hook scan runs at the start of every round**, so before each dialog *and* before acting on the answer it brings back. A hook added while the human reads the dialog is caught there even if `ConfigChange` missed it.
* **More places scanned** than the list above: skill and agent frontmatter can carry hooks (hooks reference), so `.claude/skills/`, `.claude/agents/` and plugins' skills and agents are read too; so are the command lines Claude Code was started with (`--settings`, `--plugin-dir`), which covers part of the "plugins loaded for one session" limit. Project settings are read in the project folder and every folder above it.
* **`ConfigChange` only blocks new hooks.** Blocking every change to a file that already holds such a hook would stop the user from editing their own settings, while chat approvals are already refused. So `SessionStart` records the hooks present at the start (`.local/hookguard-baseline.json`) and `ConfigChange` blocks only ones not in it. The baseline is agent-writable, which is acceptable: the per-round scan doesn't use it.
* ***skip* is the first choice** of every dialog, so a hook that picks the first option changes nothing.
* **The replaced-proposal diff (finding #7) isn't in the dialog yet:** the ledger keeps no earlier version. It stays an open question in PROGRESS.
* **From Copilot's review of PR #43:** an answer applies only if the dialog, rendered again from disk, is unchanged (a digest in the sealed state), so a test or request changed while the dialog is open is shown again rather than approved unseen; unreadable plugin metadata and an enabled plugin that can't be found count as problems; where Claude Code's launch arguments can't be read (Windows for now), chat approvals are refused; dead-end retirements are journaled like the other decisions.
* **`run_proposed = "ask"`** (§12.4.4) still waits for v0.2; the only "Run this test?" dialog in v0.1 is red-green's, which has the same guards.
