---
id: ADR-20261013-c3f7
title: Approved rule tests are not linted or reformatted
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["pyproject.toml"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-c3f7: Approved rule tests are not linted or reformatted

## Context

This repo runs `ruff check .` and `ruff format --check .` locally and in CI, and until now that included `.seamspec/tests/`. On 2026-10-13 the owner approved six rules; two of their tests have a line a few characters over the limit, and one is formatted differently from what `ruff format` would write. The agent had not run ruff on the tests before proposing them.

A locked rule test can't be tidied up afterwards. SeamSpec records a hash of the test at approval, and any edit, even whitespace, counts as tampering until a human supersedes the rule with a new one. So a linter that covers `.seamspec/` can put the repo in a state with no honest way out: CI fails on style, and the only fix is to edit an approved test. The same would happen to the nine older rule tests the day a ruff upgrade changes a formatting rule.

## Decision

1. **`.seamspec/` is excluded from ruff** (`extend-exclude` in `pyproject.toml`), next to `docs` and `notes`. Rule tests are approved records, not source code under style rules.
2. **Rule tests are linted before they are proposed**, while they can still be changed. For this repo that is the agent's job: run `ruff format` and `ruff check` on a test before calling `propose_invariant`.
3. The six tests stay exactly as the owner approved them.

**Alternatives considered:**
- **Supersede the two rules with reformatted tests.** A second review for the owner over three characters of line length, and the same problem returns with the next ruff release.
- **`# noqa` or per-file ignores.** Either means editing the approved test, or a list in `pyproject.toml` that grows with every rule.

## Enforced Invariants

None.

## Consequences

- CI no longer checks the style of rule tests. Their behavior is still checked on every commit, which is what they are for.
- A note for the product: any project that lints its whole tree will meet this the first time a rule test doesn't match its linter. SeamSpec could say so at `init`, or `doctor` could warn when a linter config covers `.seamspec/`. Not built; recorded in `docs/PROGRESS.md` as a finding.
