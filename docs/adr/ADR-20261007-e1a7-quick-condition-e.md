---
id: ADR-20261007-e1a7
title: Quick condition E - rules written in CLAUDE.md, and how its result is read (fixed before running)
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-07
scopes: ["bench/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261007-e1a7: Quick condition E - rules written in CLAUDE.md, and how its result is read

> Written **before** any condition-E run. The reading rule below must not change after the first E run.

## Context
The rough benchmark passed (ADR-20261006-b270), but B (SeamSpec advisory) did as well as C (enforced). That suggests most of the benefit came from the agent *knowing* the agreements. A plain `CLAUDE.md` gives that too, at no cost. Condition E, "rules written in `CLAUDE.md`", was planned for the week-5 full run (b270, decision 3). The owner chose a quick, early version, because its answer could change positioning and priorities before more is built.

## Decision
1. **Condition E** (`bench/harness/prepare.py`):
   - The task repo gets a `CLAUDE.md` with the same rules (title and assertion) and the same dead end (approach and symptom) that B and C get through the ledger.
   - It's written as a careful teammate would write it, including the same "ask first" habit SeamSpec's directive asks for: *"If a request would break one of these agreements, don't change it on your own… ask the user first."*
   - No SeamSpec, no tests, no hooks, no plugin.
   - **The batch:** both tasks, 3 runs, Sonnet 5.5, API key (about $6–7), label `rough-1e`. The tasks, prompts, oracle, detectors and harness settings are exactly those of `rough-1`.
2. **Comparison:** `python -m bench.compare --base rough-1 --with rough-1e` puts E next to `rough-1`'s A–D. This is a weaker design than running all five side by side on one day; the week-5 full run does that.
3. **Reading rule** (`read_condition_e`, fixed now). E is compared with C, the product as shipped, on the pass bar's own metric: violations in the final working tree. With V(C) = 2 from `rough-1`:
   - **V(E) ≥ V(C) + 3 (≥ 5):** *SeamSpec's memory beats plain notes.* The positioning in b270 stands.
   - **V(E) ≤ V(C) + 1 (≤ 3):** *plain notes match SeamSpec's memory.* Positioning shifts to what notes can't do: tests that prove each rule and catch drift, protection against rewritten tests, CI for the whole team, and the approval record.
   - **V(E) = V(C) + 2 (4):** *unclear*; decide at the full run.
4. **A new secondary measure: violations committed at `HEAD`,** not only those left in the working tree. It's reported for every run from now on, and computed for `rough-1` from its cached working copies.
   - It separates "broke the rule and committed it" from "changed it but waited for the human".
   - It informs the write-up but doesn't decide the reading. This is the "uncommitted changes pending a supersede" number announced in b270, decision 3.
   - Computed now for `rough-1`: A 9, B 0, C 0, D 6 committed. Before this, the per-run results only showed working-tree violations: A 9, B 1, C 2, D 6.
5. **The pass bar isn't applied to E or to partial batches.** `summary()` applies it only when A–D are present in one batch.

**Alternatives considered:**
- *Wait for the week-5 full run:* the owner chose early, cheap information.
- *E without the "ask first" line:* rejected. B and C get SeamSpec's directive with that habit, and leaving it out would compare notes against notes plus a protocol, overstating SeamSpec's advantage.

## Enforced Invariants
None.

## Result (2026-10-07)
`rough-1e`: 6 runs, $4.84, no errors (`docs/benchmark/rough-1e.md`).

| | A | B | C | D | **E** |
|---|---|---|---|---|---|
| Violations (working tree) | 9 | 1 | 2 | 6 | **0** |
| Committed at HEAD | 9 | 0 | 0 | 6 | **0** |
| Dead-end reappearances | 4 | 0 | 0 | 4 | **0** |
| Median cost per run | $0.95 | $1.20 | $1.22 | $1.14 | **$0.78** |

**Reading: notes match SeamSpec's memory** (V(E) = 0 ≤ V(C) + 1).
- With a careful model and well-written notes that include "ask first", knowing the agreements was enough. The notes-only agent refused and asked in every T2 conflict, as SeamSpec's agent did.
- E was about 36% cheaper per run than C.
- Per decision 3, positioning shifts to what notes can't do: capturing agreements as they're made, human approval, tests that prove each rule and catch drift, protection against rewritten tests, CI for the whole team, and one source for every tool.
- What follows for the product is decided in ADR-20261007-ac04.

## Consequences
* The full run in week 5 still includes E side by side with A–D (b270, decision 3).
* The result goes into an addendum to this ADR, or a short result ADR.
