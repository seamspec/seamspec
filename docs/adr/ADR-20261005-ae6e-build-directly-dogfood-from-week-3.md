---
id: ADR-20261005-ae6e
title: Build SeamSpec directly from SPEC.md; dogfood from week 3
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["docs/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-ae6e: Build SeamSpec directly from SPEC.md; dogfood from week 3

## Context
`docs/SPEC.md` (~3,400 lines) is a complete, peer-reviewed design for v0.1. Before starting week 1 we asked whether to drive the build with a spec-driven tool such as OpenSpec, or build directly while keeping a record of progress and decisions.

The design work is already done and reviewed. What the next six weeks need is fast building by one person, plus a record of *why* the design changes as code meets reality.

## Decision
Build directly from SPEC.md, with this lightweight process:

1. **SPEC.md stays current.** When the code differs from the spec, update the affected section in the same commit.
2. **Rule of thumb: anything that changes or adds to the spec gets an ADR** in `docs/adr/` (format: SPEC §10.3; file name `ADR-YYYYMMDD-xxxx-slug.md`). Plain implementation detail doesn't.
3. **Progress is tracked on GitHub:** one milestone per roadmap week (SPEC §22) plus `v0.2`, each with a tracking issue whose checklist mirrors the §22 deliverables and exit criteria.
4. **Private handoff notes** stay in `notes/CONTEXT.md` (git-ignored).
5. **From week 3, SeamSpec governs its own repo** (`.seamspec/`): its own behavior is locked with SeamSpec invariants, and `docs/adr/` moves to `.seamspec/adrs/` with `git mv`.

**Alternatives considered:**
- **OpenSpec:** rejected for this project. It would duplicate SPEC.md into a second source of truth, add ceremony after the design was already reviewed, and weaken the launch story ("SeamSpec is built with SeamSpec"). Worth trying on another project to understand spec-first users.
- **SPEC edits only, no ADRs:** rejected. The spec would show *what* changed but lose *why*.

## Enforced Invariants
None (process decision).

## Consequences
* Every spec-changing commit carries an ADR, so the history of design changes is reviewable.
* ADRs already use SeamSpec's own format, so moving them into `.seamspec/adrs/` in week 3 needs no conversion.
* Dogfooding from week 3 gives real usage, a launch demo and benchmark material.
* SPEC §26 records decisions up to 2026-10-05; later decisions live in ADRs.
