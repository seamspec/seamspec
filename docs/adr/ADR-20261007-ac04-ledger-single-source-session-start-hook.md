---
id: ADR-20261007-ac04
title: The ledger stays the single source; a session-start hook adds the current rules (no notes files)
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-07
scopes: ["seamspec/adapters/claude.py", "seamspec-plugin/hooks/hooks.json", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261007-ac04: The ledger stays the single source; a session-start hook adds the current rules

## Context
The quick condition-E run (ADR-20261007-e1a7) showed that plain notes in `CLAUDE.md` matched SeamSpec's memory, at about 36% lower cost per run. With notes, the agreements are in the agent's context from the first moment of a session. With SeamSpec, the agent fetches them: it calls `get_constraints` each session, and the MCP tool definitions stay in context.

**The first proposal:** SeamSpec writes a generated `AGREEMENTS.md`, and `CLAUDE.md` imports it with an `@` line.

**The owner contested it, rightly.**
- `CLAUDE.md` is the team's own, human-written instructions, and filling it with generated rules is clutter.
- A second file duplicates the ledger, which already is the record of decisions, and two copies of the truth tend to drift.
- SeamSpec already reaches the agent through hooks.

## Decision
1. **The ledger (`.seamspec/`) is the single source of truth.** SeamSpec writes no notes files and doesn't add rules to `CLAUDE.md`. The small directive block `init` manages is unchanged.
2. **A `SessionStart` hook adds a short summary of the current agreements to the agent's context:**
   - **what it lists:** approved (LOCKED) rules and active dead ends, one line each, plus the number of items waiting for the human's review;
   - **how it's built:** freshly from the ledger at every session start, including after `clear` and `compact`, so it can't drift and nothing is written to disk;
   - **size** (amended by ADR-20261011-6b2d: 8,000 characters, five steps, and a dead end always keeps its reason): it stays within 3,000 characters by shrinking detail, never by dropping a rule: every rule in full if it fits; else one line per rule (id, title, scope); else counts per area. Each smaller level points to `get_constraints` for the full rules. Marking some rules "critical" so they always show in full is left to v0.2;
   - **modes:** it runs in every mode, advisory included, because it's context, not enforcement;
   - **failure:** it fails open, adding nothing on any error.
3. **Detail still comes on demand:**
   - the edit-time hook gives the full rules for the file being edited;
   - `get_constraints` gives detail when asked;
   - the directive's "call `get_constraints` first" stays, but the agent no longer has to do it to learn what's in force.
4. **Other hosts (v0.2):** where a host supports hooks, it gets the same session-start context. A generated rules file is only a per-host fallback for hosts with no way to inject context, and it would be a rendering of the ledger, not a second source.
5. **Measurement:** the week-5 full run runs C with this hook against E (notes) and F (ADRs only) (ADR-20261006-b270, decision 3). A cost reduction is expected but not assumed.

**Alternatives considered:**
- *Generated `AGREEMENTS.md` plus an `@` line in `CLAUDE.md`:* rejected (see Context).
- *Write the rules into SeamSpec's existing `CLAUDE.md` block:* rejected as clutter. The block grows with every rule and adds context cost on every turn in every session.
- *Keep relying on the agent calling `get_constraints`:* kept as a fallback only. A tool call per session costs more, and depends on the agent remembering to make it.

## Enforced Invariants
None yet. Candidate once built: "the session-start context never exceeds its size cap".

## Consequences
* `seamspec-plugin/hooks/hooks.json` gains a `SessionStart` hook, and `seamspec hook claude session-start` produces the summary. SPEC §16.1 moves the session-start hook from v0.2 to v0.1 with this job.
* Positioning (ADR-20261006-b270, decision 2) is refined: *"your agreements, approved and proven by tests that CI enforces, put in front of every agent"*. The memory is the delivery mechanism, not the pitch.
