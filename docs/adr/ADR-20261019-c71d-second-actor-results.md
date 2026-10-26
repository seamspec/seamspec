---
id: ADR-20261019-c71d
title: "Result: with SeamSpec, nothing broken reached main, whoever made the change"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-19
scopes: ["docs/benchmark/", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261019-c71d: Result of the second-actor benchmark

## Context

The owner ran `second-1` on 2026-10-19 (36 runs, $13.58) under ADR-20261019-5f3b. A calibration first added a "blocked although nothing was broken" count (PR #86), and a harness crash at T2 was fixed and resumed (PR #87). The write-up is [`second-1.md`](../benchmark/second-1.md).

## Decision: the result, and what may be said

**PASS.**

| | Broken by the teammate's agent | Landed on `main` |
|---|---|---|
| Nothing | 12 | 12 |
| Person-written notes | 0 | 0 |
| The author's agent's notes | 6 | 6 |
| SeamSpec | 2 | **0** |

**Hand edits (demonstration):** 11, 11, 10 and **0** of 21 landed, in the same order.

**Reported next to it:** SeamSpec's CI also blocked 2 pushes the hidden tests call fine, because the captured rules pin details the user stated.

**The claims table of ADR-20261018-a4c2 gains:**

| Claim | Status | Source |
|---|---|---|
| **With SeamSpec, a broken agreement doesn't reach `main`, whoever made the change** | **Yes** | `second-1` |
| A teammate's agent breaks fewer agreements with SeamSpec than with notes a person wrote | No (match) | `second-1` |
| ... than with the author's agent's notes | No (unclear) | `second-1` |

**Positioning:** the pitch adds the team case. *A notes file is advice to whichever agent reads it; SeamSpec's rules are tests CI runs on every push. Whoever changes the code, a teammate, their agent or a person by hand, a broken agreement doesn't reach `main`.* The cost is stated with it: the captured rules can block a change the team didn't mean to forbid, which then goes through a supersede.

## Alternatives considered

- **Count the hand edits as a measured advantage:** they are decided by construction. They stay a demonstration, as the plan said.
- **Drop the 2 "blocked although nothing was broken" pushes as noise:** they are the honest price of the guard, and the plan required showing them.

## Enforced Invariants

None.

## Consequences

- SPEC §23 and §24 record the result and the claim.
- **Product follow-up:** a teammate who never ran `seamspec init` gets "not trusted" from `seamspec verify`. Their agent should be told to run `seamspec init`, or `verify` should say so.
- With this, every planned benchmark has run. Next, as agreed earlier: the README, using only the allowed claims across ADR-20261013-e2b6, ADR-20261018-a4c2 and this ADR.
