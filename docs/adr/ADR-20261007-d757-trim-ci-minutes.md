---
id: ADR-20261007-d757
title: Trim SeamSpec's own CI to fit the Actions minutes of a private repo
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-07
scopes: [".github/workflows/tests.yml"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261007-d757: Trim SeamSpec's own CI to fit the Actions minutes of a private repo

## Context
On 2026-10-07 GitHub stopped starting jobs: *"recent account payments have failed or your spending limit needs to be increased"*. The `seamspec` organization is on the Free plan, and private repos get a limited monthly allowance of Actions minutes, with **macOS minutes counted 10×**. The owner fixed billing the next morning.

Each push ran 7 jobs: Python 3.11–3.14 on Linux, Python 3.12 on macOS, vitest, and the SeamSpec check. That's about 22 billable minutes per push, roughly 15 of them from macOS. With many PR pushes a day, the allowance lasted only a few days. A Team plan adds only about 50% more minutes, so it isn't a fix on its own (discussed with the owner).

## Decision
1. **Pull requests** run Python **3.11 and 3.14** (the oldest and newest supported), plus vitest and the SeamSpec check (`doctor --ci`, `verify --all --ci`). `ci-ok` gates on these.
2. **Pushes to `main`** run the full Python 3.11–3.14 matrix, and **macOS** (Python 3.12) in a separate `test-macos` job. A problem specific to one platform or version shows up right after merge, on `main`.
3. **Concurrency:** a new push to a PR cancels the run still going for its previous commit. Runs on `main` always finish.
4. **Cost:** a PR push drops from about 22 to about 5 billable minutes.

**Alternatives considered:**
- *Upgrade to Team for minutes:* rejected as the fix; it adds about 50% and costs per user. Team stays worth considering later to *enforce* `ci-ok` on this private repo (rulesets).
- *Drop macOS entirely:* rejected. Path handling, `/bin/sh` and process groups have bitten macOS before (the owner develops on macOS); once per merge is enough.
- *Make the repo public for free minutes:* tied to the release decision (ADR-20261005-3adc), not now.

## Enforced Invariants
None.

## Consequences
* Regressions specific to Python 3.12, 3.13 or macOS can now reach `main` and show up there, not on the PR. The fix is a follow-up PR.
* SPEC §21 describes the new matrix.
