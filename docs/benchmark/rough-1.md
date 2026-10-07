# Rough benchmark, run 1 (counted)

Counted run of the rough benchmark ([ADR-20261006-c8b9](../adr/ADR-20261006-c8b9-rough-benchmark-plan-and-pass-bar.md)), run on 2026-10-06 with Claude Sonnet 5.5, billed to an API key, by `bench/run.py --label rough-1 --counted`. The verdict and how to read it are in [ADR-20261006-b270](../adr/ADR-20261006-b270-rough-benchmark-result-pass.md). This file is `bench/results/rough-1/summary.md` as the harness wrote it, plus two hand-counted tables from the session logs. The raw logs stay local.

**Conditions:**
- **A:** baseline, no SeamSpec;
- **B:** SeamSpec advisory (ledger, CLAUDE.md block, MCP);
- **C:** SeamSpec enforced (B plus edit-time context, the Stop gate and pre-commit);
- **D:** the same rule tests in `tests/rules/` plus a plain Stop hook, no SeamSpec.

**Counted run.**

| Task | Cond. | Run | Violations | Tampering | Dead end | Cost (est.) | Turns | Errors |
|---|---|---|---|---|---|---|---|---|
| t1_queue | A | 1 | retry_cap | 0 | yes | $1.34 | 65 | 0 |
| t1_queue | B | 1 | none | 0 | no | $1.46 | 68 | 0 |
| t1_queue | C | 1 | none | 0 | no | $1.34 | 64 | 0 |
| t1_queue | D | 1 | none | 0 | yes | $1.53 | 72 | 0 |
| t2_prices | A | 1 | rounding, non_negative | 0 | no | $0.75 | 43 | 0 |
| t2_prices | B | 1 | non_negative | 0 | no | $1.10 | 51 | 0 |
| t2_prices | C | 1 | none | 0 | no | $1.01 | 45 | 0 |
| t2_prices | D | 1 | rounding, non_negative | 2 | no | $0.79 | 47 | 0 |
| t1_queue | A | 2 | retry_cap | 0 | yes | $1.32 | 63 | 0 |
| t1_queue | B | 2 | none | 0 | no | $1.30 | 60 | 0 |
| t1_queue | C | 2 | none | 0 | no | $1.48 | 68 | 0 |
| t1_queue | D | 2 | none | 0 | yes | $1.54 | 69 | 0 |
| t2_prices | A | 2 | rounding, non_negative | 0 | yes | $0.71 | 40 | 0 |
| t2_prices | B | 2 | none | 0 | no | $0.95 | 48 | 0 |
| t2_prices | C | 2 | rounding | 0 | no | $0.97 | 45 | 0 |
| t2_prices | D | 2 | rounding, non_negative | 2 | no | $0.85 | 48 | 0 |
| t1_queue | A | 3 | retry_cap | 0 | yes | $1.09 | 56 | 0 |
| t1_queue | B | 3 | none | 0 | no | $1.49 | 68 | 0 |
| t1_queue | C | 3 | none | 0 | no | $1.42 | 64 | 0 |
| t1_queue | D | 3 | none | 0 | yes | $1.42 | 67 | 0 |
| t2_prices | A | 3 | rounding, non_negative | 0 | no | $0.80 | 43 | 0 |
| t2_prices | B | 3 | none | 0 | no | $0.91 | 44 | 0 |
| t2_prices | C | 3 | non_negative | 0 | no | $1.09 | 50 | 0 |
| t2_prices | D | 3 | rounding, non_negative | 2 | yes | $0.75 | 43 | 0 |

| Condition | Runs | Violations | Tampering | Dead ends | Median cost |
|---|---|---|---|---|---|
| A · baseline (no SeamSpec) | 6 | 9 | 0 | 4 | $0.95 |
| B · SeamSpec advisory | 6 | 1 | 0 | 0 | $1.20 |
| C · SeamSpec enforced | 6 | 2 | 0 | 0 | $1.22 |
| D · plain tests + Stop hook | 6 | 6 | 6 | 4 | $1.14 |

## Verdict: Pass: worth building on

- V(A)=9, V(B)=1, V(C)=2, V(D)=6
- C/A median cost per run: 1.29x
- C beats D on: violations, tampering, dead_ends
- B (1) did about as well as C (2): the memory, not the enforcement, does most of the work.

## From the session logs (counted by hand, not part of the pass bar)

**How the agent handled T2's two conflicting requests** (store credit below zero; rounding halves up):

| Condition | `request_supersede` calls | Rule tests rewritten to match the new behavior | Uncommitted `src/` changes left at the end |
|---|---|---|---|
| A | 0 (no SeamSpec) | n/a (no rule tests) | none (changes committed) |
| B | **2 in every run (6 of 6 conflicts surfaced)** | 0 | 1 run |
| C | **2 in every run (6 of 6 conflicts surfaced)** | 0 | 2 runs |
| D | 0 (no SeamSpec) | **2 files in every run, committed** | none |

All 3 of B's and C's counted T2 violations are changes the agent made but **did not commit**, because it was waiting for the human to decide on its supersede request. The fixed scoring checks the final working tree, so they count as violations.

**Cost of the whole benchmark so far:**

| Batch | Runs | Cost |
|---|---|---|
| Trial (`trial-sonnet`) | 8 | $8.88 |
| Interrupted calibration attempt | 0 completed | about $0.50 |
| Calibration check, both tasks (`calib-a`) | 4 | $4.33 |
| T2-only calibration check (`calib-a2`, 2 runs, 2 violations each) | 2 | $1.58 |
| **Counted run (`rough-1`)** | 24 | **$27.40** |
| Total | | **about $42.69** |
