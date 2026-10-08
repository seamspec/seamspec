---
id: ADR-20261008-5d1e
title: Chat approvals off by default until Claude Code shows the whole dialog (verification 2)
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-08
scopes: ["seamspec/core/config.py", "seamspec/chat_review.py", "seamspec/templates/**", "seamspec-plugin/skills/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261008-5d1e: Chat approvals off by default until Claude Code shows the whole dialog (verification 2)

> Amends ADR-20261006-c300 (approvals in chat), which stays ACCEPTED: the design and its guards are unchanged. Only the default changes, along with how a declined dialog is handled.

## Context

Verification 2 of ADR-20261006-c300 was the owner's click-through, the day #43 merged. Three rules were proposed for this repo, and the owner asked to review them in chat: in the terminal CLI (Claude Code 2.1.294) and in the Claude desktop app (its bundled Claude Code, 2.1.293).

| Where | What happened |
|---|---|
| **Terminal CLI** | The agent called `open_review`; Claude Code showed SeamSpec's form. The message was folded to about three lines (the header and *"Proposed rule 1 of 3 · inv_…"*), then *"… (+41 more lines)"*. Ctrl+O didn't expand it. The rule, the scope and the **test were hidden**; field titles were cut off too (*"Reason (required to r…"*). |
| **Claude desktop app** | **No dialog appeared.** The agent called `open_review` once; each of the three dialogs came back `decline` straight away. SeamSpec counted a decline as the human skipping the item, so the session reported *"all three skipped"*. |

Approval in SeamSpec means the human has seen the full test (SPEC §12.4.3 rule 4, §11.1). In the CLI the dialog can't meet that, and in the desktop app it doesn't reach the human at all. Nothing was approved in either run: all three rules are still PROPOSED.

## Decision

1. **`[review] chat_approvals` defaults to `false` in every mode** (it was `true`, except in strict mode). `init` writes `chat_approvals = false` with a comment saying why. A project can still turn it on, accepting what its client shows. The `ConfigChange` hook and the session-start baseline only act when it's on, as before.
2. **A declined dialog stops the review.** It used to count as *skip* and go on to the next item, which turned an app that declines unseen into "the human skipped everything". Now the review stops (decisions already made in it stay; nothing else changes), journals `chat_dialog_declined`, and tells the agent: *"If no dialog appeared, this app can't show SeamSpec's dialogs."* The form's own *skip* choice is still how a human skips and goes on.
3. **The skills and the protocol block point to `seamspec review` in a terminal again,** naming the desktop app's terminal panel. They mention `open_review` only for projects that turned chat approvals on.
4. **Everything else in ADR-20261006-c300 stays:** the tool, the hook guards, `decided_via` and the journal fields, and the answer-to-content binding. When Claude Code shows the whole message (or another client does), the default can flip back after another click-through.

**Alternatives considered:**
- **Keep it on, and put only the rule's title and a file path in the dialog.** Rejected for now: the human would still approve without the test in front of them.
- **Build the local review page now** (ADR-20261006-c300 option B: SeamSpec opens a page in the browser itself, so the link never passes through the agent). Deferred: the owner chose to dogfood with `seamspec review` first and build the page only if the terminal step turns out to be a real pain.
- **Remove `open_review`.** Rejected: the tool, its guards and its tests are sound, and it costs about 140 tokens of tool definitions. It answers `chat_approvals_off` while off.

## Follow-ups (2026-10-08)

* **Full-screen CLI, tried again:** with chat approvals turned on for the experiment only, the owner ran Claude Code in a full-screen macOS Terminal window. The dialog was folded the same way and the test stayed hidden, so the pane size isn't the cause. The owner pressed Esc and nothing changed; the setting was switched back.
* **The agent opens the review for the user (owner's choice).** The lock, supersede and status skills and the protocol block now tell the agent to offer to open `seamspec review` in a terminal the user types into, such as a tab in the Claude desktop app's terminal panel. The agent never runs it in its own shell (no terminal there, so it refuses anyway) and never types its answers. Like the TTY check itself, this is a speed bump, not a boundary. It keeps the approval with the human while removing most of the "go to a terminal" step. A local review page in the browser (ADR-20261006-c300 option B) stays the next step if dogfooding shows that isn't enough.

## Enforced Invariants

None new. The three rules proposed for the click-through protect the chat path's guards. The owner approved them with `seamspec review` on 2026-10-08, after their tests were strengthened following a review by the agent in the owner's session:
* `inv_aa498871`: the agent never supplies approval dialog text;
* `inv_6bae33cf`: chat approval refuses when a hook could answer;
* `inv_79b867d5`: every human decision records where it was made.

## Consequences

* Approving goes back to `seamspec review` in a terminal (in the desktop app, its terminal panel). Hands-on finding #8 (leaving the chat to approve) is only partly solved.
* SPEC §7.3, §9.5, §11.5 and §16.1 are updated.
* Open: check again when Claude Code changes how it shows MCP form dialogs, and decide on the review page after dogfooding.
