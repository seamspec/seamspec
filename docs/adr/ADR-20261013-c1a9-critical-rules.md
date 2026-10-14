---
id: ADR-20261013-c1a9
title: "Critical rules: a few rules the agent always sees in full"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/core/models.py", "seamspec/schemas/v1/invariant.json", "seamspec/core/lifecycle.py", "seamspec/adapters/claude.py", "seamspec/cli.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-c1a9: Critical rules: a few rules the agent always sees in full

## Context

The session-start summary (ADR-20261007-ac04, ADR-20261011-6b2d) puts the rules in force in front of the agent at the start of each session. To stay under Claude Code's hook limit it shrinks as the ledger grows: rules in full, then titles with scope, then titles, then counts per area. In a large ledger a rule that must never be missed can end up as one count among many, and the agent sees it only when it asks `get_constraints` for that file.

ADR-20261007-ac04 planned a "critical" marking for v0.2: such rules always show in full. The owner moved it into v0.1 (ADR-20261013-f4a8). It changes the record format, so before the first release is the time.

## Decision

1. **A field on the rule record:** `critical: bool`, default `false`, in the model and in `invariant.json`. Records without it read as `false`.
2. **What it changes:** how the rule is shown, never whether it is enforced. Every locked rule runs at Stop, pre-commit and CI exactly as before.
   - **Session-start summary:** critical rules come first, under their own heading, in full (assertion up to 400 characters, up to four scope paths), at every level, including the "counts per area" level. Only the other rules and the dead ends shrink.
   - **`get_constraints` / `seamspec context` / edit-time context:** `[LOCKED, CRITICAL]`.
   - **`seamspec review`** and the chat dialog: a line saying so, and for a proposal that the agent suggested it.
   - **`seamspec spec`:** a "Critical" line; **`seamspec status`:** a count.
3. **Who sets it:** a human. The agent may *suggest* it when proposing (`propose_invariant(critical=true)`); the review shows the suggestion and approving keeps it. A human sets or clears it on a proposed or locked rule with `seamspec critical <id> [--off]`, which needs a terminal, like approvals. Each change is a journal note (`critical_marked` / `critical_cleared`).
4. **Not frozen, but visible.** Changing the mark is not a status change, so the forward-only check in CI allows it. `doctor --ci` warns when a pull request clears the mark on a locked rule, so a reviewer sees it.
5. **Meant for a few.** `doctor` warns when more than 10 locked rules are critical: a mark on everything protects nothing.

**Alternatives considered:**
- **Freeze it like the rule's text** (only a supersede could change it). The mark is about attention, not behavior; making it as heavy as a supersede would discourage using and correcting it.
- **Let the agent set it directly.** It would let the agent decide which rules get attention; the agent may suggest, the human decides.
- **Critical rules as a stricter gate** (block earlier, refuse more). Every locked rule already blocks; a second tier of enforcement would make the others look optional.
- **Ask at every approval.** One more question on every rule, for a mark most rules shouldn't have.

## Enforced Invariants

To be proposed: "a critical rule is shown in full in the session-start summary whatever the size of the ledger".

## Consequences

- The record format gains one optional field before the first release; no migration needed.
- The agent's `propose_invariant` tool gains an optional argument (still under the tool-definition token budget).
- The mark isn't covered by the rule's hashes: an agent with shell access could edit it in the record, as it could edit other unfrozen fields. The CI warning and the journal note make a cleared mark visible.
