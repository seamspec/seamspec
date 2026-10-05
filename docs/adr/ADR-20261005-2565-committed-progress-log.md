---
id: ADR-20261005-2565
title: Track progress in a committed PROGRESS.md, with CLAUDE.md as the agent entry point
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["docs/**", "CLAUDE.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-2565: Track progress in a committed PROGRESS.md, with CLAUDE.md as the agent entry point

## Context
ADR-20261005-ae6e tracks progress with GitHub milestones and tracking issues, and keeps handoff notes in `notes/CONTEXT.md`. But `notes/` is git-ignored, so it exists on one machine only. An agent or person starting from the repo (a cloud agent, another machine, a future contributor) can't see it, and GitHub issues only help if the newcomer has access and knows to look. The work must be handoff-ready from the repo alone.

## Decision
This amends ADR-20261005-ae6e points 3 and 4; the rest of it stands.

1. **`docs/PROGRESS.md` (committed) is the single place to see where the build stands:** current week, Done (dated, with pointers), In progress, Next, Open questions, and how to pick up the work.
2. **`CLAUDE.md` (committed, repo root) is the entry point for agents:** read order (PROGRESS → SPEC → week issue → ADRs) and the working rules (spec and code agree, ADRs, progress logging, clean room, model-free core).
3. **End-of-session rule:** whoever stops work updates `docs/PROGRESS.md` and ticks the week's GitHub issue checklist **in the same commit as the code**.
4. **GitHub issues stay** as the planned checklist per week; PROGRESS.md mirrors their state and adds what's in flight.
5. **`notes/CONTEXT.md` becomes private-only** (account details, publishing steps, personal reminders). Nothing in it may be needed to continue the build.
6. Process changes like this one get an ADR too (added to the table in `docs/adr/README.md`).

**Alternatives considered:**
- *GitHub issues only:* rejected. Needs access and API calls, and checklists can't hold "in progress" notes or open questions well.
- *Commit `notes/CONTEXT.md`:* rejected. It mixes private material with project state.
- *`AGENTS.md` instead of `CLAUDE.md`:* deferred. v0.1 targets Claude Code, and SeamSpec's own directive block goes into `CLAUDE.md` from week 3 (SPEC §18). Add `AGENTS.md` if non-Claude agents work on the repo.

## Enforced Invariants
None (process decision).

## Consequences
* Anyone can resume the build from a clone: `CLAUDE.md` → `docs/PROGRESS.md`.
* Every working session costs a small PROGRESS.md edit; skipping it breaks handoff.
* From week 3, `seamspec init` adds its marked block to the same `CLAUDE.md`, which the repo-level instructions above it already expect.
