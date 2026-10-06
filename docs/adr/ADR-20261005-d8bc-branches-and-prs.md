---
id: ADR-20261005-d8bc
title: All changes land through branches and pull requests
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: [".github/**", "docs/**", "CLAUDE.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-d8bc: All changes land through branches and pull requests

## Context
Up to week 1, every change was pushed straight to `main`. That means no reviewer ever sees a change before it lands: neither Copilot code review nor an agent review against the spec. CI only reports after the fact. From week 4, SeamSpec's own CI gate must block a regression on a real PR, so the repo needs a PR workflow anyway.

The org is on the free plan, so branch rulesets (required checks, required reviews, automatic Copilot review) aren't enforced on this private repo (GitHub Team is needed). It was expected that Copilot review would still run through the owner's **personal** automatic review setting. In practice no PR received an automatic request, so the agent requests the review on every PR instead (see ADR-20261005-c076).

## Decision
This amends ADR-20261005-ae6e and ADR-20261005-2565; the rest of them stands.

1. **No direct pushes to `main`.** Every change goes through a branch and a PR. On the free plan this is a working rule, not an enforced one.
2. **Branch names:** `week-N/<topic>` for roadmap work (e.g. `week-2/verifier`), `docs/<topic>`, `fix/<topic>`, `chore/<topic>`.
3. **Small PRs:** one per deliverable or coherent slice (e.g. verifier, lifecycle, review TUI), not one per week.
4. **Each PR carries its own bookkeeping:** SPEC updates, any ADR, the `docs/PROGRESS.md` update and `Part of #N` (the week's tracking issue). The PR template (`.github/pull_request_template.md`) lists these.
5. **Reviews:** CI must be green (or a GitHub outage noted in the PR), Copilot reviews (requested by the agent on every PR, since automatic requests need GitHub Team: amended by ADR-20261005-c076), and the agent that wrote the code self-reviews against SPEC before asking for a merge.
6. **The owner merges**, using **squash merge** so `main` keeps one commit per PR, and deletes the branch. Issue checklist boxes are ticked when the PR merges, not before.
7. When the repo goes public (rulesets become free), add a ruleset for `main`: require the **`ci-ok`** check, block direct pushes, and request Copilot review automatically. `ci-ok` is a summary job in `.github/workflows/tests.yml` that passes only if every matrix job passed. A ruleset can't require the workflow name `tests` (GitHub reports one `test (<os>, <python>)` check per matrix entry), and requiring those individual names would break whenever the matrix changes.

**Alternatives considered:**
- *Keep pushing to `main`:* rejected; nothing gets reviewed before it lands.
- *Upgrade to GitHub Team now to enforce rulesets:* deferred; a cost with little benefit for a solo build. Revisit at launch or when a second contributor joins.
- *One PR per week:* rejected; too large to review well.

## Enforced Invariants
None (process decision).

## Consequences
* Each change has a review point before `main`: CI, Copilot and a spec check.
* Slightly more ceremony per change (branch, PR, merge click).
* `main` history becomes one squashed commit per PR, which keeps it readable and lines it up with PROGRESS.md entries.
* Until the repo is public, discipline replaces enforcement: nothing technically stops a direct push.
