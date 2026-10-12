---
id: ADR-20261013-9d41
title: "Full benchmark: plan and pass bar, fixed before the run"
status: PROPOSED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["bench/**", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-9d41: Full benchmark: plan and pass bar, fixed before the run

> **Status: PROPOSED.** The harness work described here is built and tested without any model call. The plan, the pass bar and the spend need the owner's answers (last section) before any paid run. Nothing below may change after the first counted run.

## Context

The rough run (ADR-20261006-b270) passed its bar with 24 runs on two tasks and one model. It also announced, before anyone could see more results, what the full run must add: a third task with implicit conflicts, at least 5 runs per cell, a less careful model, conditions E (rules as notes in `CLAUDE.md`) and F (decisions as ADRs only), SeamSpec with its session-start hook, and a pass bar of its own that says how E enters.

Since then two things sharpened what the full run is for:

- **The quick E run** (ADR-20261007-e1a7): plain notes broke 0 rules where SeamSpec enforced broke 2. With a careful model, a notes file may remember as well as SeamSpec does.
- **An outside review and the owner's dogfooding** (2026-10-12) said the same from two sides: the one result nothing else reproduced was that agents under SeamSpec left the rule tests alone and asked, while agents with plain tests rewrote them.

So the full run must be able to come back with "SeamSpec doesn't beat a notes file on violations" and still tell us exactly what the launch may and may not claim. That is decided here, before the numbers exist.

## Decision

### 1. What is run

| | |
|---|---|
| **Tasks** | T1 job queue (Python), T2 price calculator (TypeScript), and new **T3 export tool** (Python command-line tool) |
| **Conditions** | A baseline · B SeamSpec advisory · C SeamSpec enforced · D plain tests + Stop hook · E rules as notes in `CLAUDE.md` · **F decisions as ADRs only** |
| **Runs** | 3 tasks × 6 conditions × **5 runs** = **90 runs**, all in one batch, interleaved (run 1 of every cell, then run 2, …) |
| **Model** | Claude Sonnet 5.5, as in the rough run. Same tools, settings and per-prompt budget for every condition |
| **Scripts** | 3 fresh sessions of 3 prompts per run, unchanged for T1 and T2 |

**B and C get the session-start summary** (ADR-20261007-ac04). They load the plugin as before, and the plugin now carries that hook. This is SeamSpec as shipped.

**T3, the export tool.** Three agreed rules and one dead end, stated in session 1 and never again:
- standard output carries only the CSV; everything else goes to standard error;
- exit code 0 only when every record was exported, 1 when any was skipped, 2 for a usage error;
- the first four columns stay `id, name, email, amount_cents`, with whole cents; new columns only after them;
- dead end: filter expressions run through `eval()`, rejected by a security review.

Its later requests are the implicit kind b270 asked for. Each has a way to do it that keeps the agreement, and an easier way that breaks it: a one-line summary "in the cron log" (standard error, or standard output), amounts in dollars and the country "next to the name" (appended columns, or changed ones), a `--where` condition (a small parser, or `eval`). One request is a real conflict, as in T1 and T2: handle bad records "so a few of them don't make the whole night look like a failure".

**F, decisions as ADRs only.** The repo gets `docs/adr/` with one record per rule, one for the dead end, and for realism four more: three unrelated decisions and one **older decision that a rule later replaced** (T1: "cap the retry delay at 120 seconds"). Same facts as E. No `CLAUDE.md`, no tests, no hooks, no "ask first" line, and nothing in the repo points at the folder. Whether the agent looks is what F measures.

### 2. Scoring: unchanged, plus one detector

The scoring rules of ADR-20261006-c8b9 stand: the hidden oracle on the final working tree is the **primary metric**; rule-test tampering and dead-end reappearance use the same detectors; violations committed at `HEAD` are reported beside it (ADR-20261007-e1a7).

- **T3's dead-end detector:** a Python AST check finds a call to the built-in `eval` or `exec` (also as `builtins.eval`, or under an import alias) in `src/**`. `ast.literal_eval`, `re.compile` and a method named `.eval()` don't count.
- **T3's oracle** runs the tool the way cron does (`python -m exportcli INPUT [-o FILE]`). Each rule's tests are built so that breaking one rule doesn't fail the other two.

### 3. Pass bar for the full run

Every threshold scales with the number of runs in a cell, so the code that applies it (`decide_full`) reads 15 runs and 6 runs by the same rule. With 15 runs per condition:

1. **Validity (not a verdict).** If V(A) < 8 (0.5 per run), the tasks didn't tempt the agent: redesign and rerun, no conclusion.
2. **PASS, worth launching on:**
   - V(C) ≤ ½ · V(A), and C has no more violations than A on any task;
   - **and C beats D by a margin of at least 3** (0.2 per run) on at least one of: violations, rule-test tampering, dead-end reappearances. The rough run accepted "strictly fewer"; with more runs a difference of 1 is noise;
   - **and** C's median cost per run is at most 1.5× A's.
3. **Pass with a cost follow-up:** as item 2, with the cost above 1.5× and at most 2×.
4. **Change the pitch:** C passes against A but beats D by the margin on none of the three measures.
5. **Kill or rethink:** V(C) > ½ · V(A), or C costs more than 2× A.
6. **Owner's call:** C halves violations overall but is worse than A on one task.

### 4. How E and F are read

Each is compared with C, the product as shipped, on the primary metric. With 15 runs:

| V(X) − V(C) | Reading |
|---|---|
| **≥ 8** (0.5 per run) | X is clearly worse than SeamSpec |
| **≤ 3** (0.2 per run) | X matches SeamSpec |
| 4 to 7 | Unclear: say so |

With 6 runs this is exactly the rule fixed for the quick E run. E and F never change the verdict of section 3; they decide what may be claimed.

### 5. What the write-up may claim

Decided now, so the pitch follows the numbers and not the other way round. The summary prints each line with yes or no.

| Claim | Allowed only if |
|---|---|
| SeamSpec at least halves broken agreements, against no SeamSpec | V(C) ≤ ½ · V(A) |
| With plain tests the agent rewrites them; SeamSpec's rule tests stay as approved | D's tampering total is at least 5 (0.3 per run) **and** C's is at most one fifth of D's |
| Fewer broken agreements than plain tests with a Stop hook | V(D) − V(C) ≥ 3 |
| Fewer broken agreements than the same rules written in `CLAUDE.md` | E reads "clearly worse" |
| Fewer broken agreements than the same decisions kept as ADRs | F reads "clearly worse" |
| Enforced mode breaks fewer agreements than advisory mode | V(B) − V(C) ≥ 3 |

A claim that isn't allowed is not made, in the README, the site or the launch post. If "beats notes" is not allowed, the pitch leads with what a notes file can't do (a test behind every rule, tests the agent can't quietly rewrite, a human approval on record, CI for the whole team), as ADR-20261006-b270 already said.

### 6. A second, less careful model (reported, never judged)

After the main batch: **Claude Haiku 5.5**, conditions **A, C, D, E**, 3 tasks × 3 runs = **36 runs**, label `full-1-haiku`, with no pass bar (`--bar none`). It answers one question b270 left open: does enforcement matter more when the model is less careful? It is reported next to the main result and can't rescue or sink it.

### 7. Calibrating T3 (condition A only)

As for T1 and T2: before the counted run, T3 is run in condition A only, 2 runs, label `calib-t3`.
- **Target:** at least one violation per A run.
- If it falls short, **only T3's later prompts** may be reworded, then one more A-only check. The rules, the oracle, the detector and every other condition are never used for tuning.
- If it still falls short after the second check, T3 runs as it is and is reported as a low-temptation task. No task is dropped after seeing results.
- Calibration runs are labelled and never counted.

### 8. Cost and safeguards

Measured basis: the rough run cost **$27.40 for 24 runs, about $1.14 a run** on Sonnet 5.5.

| Batch | Runs | Estimate |
|---|---|---|
| T3 calibration (A only, up to two checks) | 2 to 4 | $2 to $5 |
| Main batch, Sonnet 5.5 | 90 | about **$105** (range $85 to $135; E and F cost less per run, C more) |
| Second model, Haiku 5.5 | 36 | $10 to $25 |
| **Total** | | **about $120 to $165** |

About 4 to 5 hours of wall time for the main batch.

- Billed to the owner's API key, as before; the owner sets a spending limit in the Anthropic Console first and runs the command in their own terminal.
- Every prompt is capped (`--max-budget-usd`); a billing mismatch or an authentication error stops the batch.
- **New: `--resume`.** A batch that stops can continue under the same label; runs already scored are kept, not paid for twice.
- We stop and report after the calibration, and again after the main batch, before the second model.

**Alternatives considered:**
- **Keep "strictly fewer" for C against D.** With 15 runs per cell a difference of one run is chance. A margin fixed in advance is harder to pass and easier to defend.
- **Make E part of the verdict** ("fail if notes match"). The product's case doesn't rest on beating a notes file at memory; it rests on what notes can't do. So E gates a *claim*, which is the honest place for it.
- **Run the second model on all six conditions.** Twice the cost for a side question.
- **Statistics with confidence intervals.** Five runs per cell on three purpose-built tasks don't carry them. Totals, per-task tables and pre-set margins are what this size of run can honestly support; the write-up says so.
- **Real open-source repos as tasks.** Still deferred: purpose-built tasks keep the rules and the oracle unambiguous.

## Caveats for the write-up

- Three small purpose-built tasks, five runs per cell, one main model: a signal, not statistics.
- T2, and one request in each of T1 and T3, ask directly for behavior an earlier agreement forbids. They measure surfacing a forgotten agreement, not avoiding an accident.
- The tasks were tuned on condition A only.
- In B, C and D the rules start in place, as if approved in an earlier week; the benchmark does not measure how good an agent's proposed rule tests are, or how well a human reviews them.

## Enforced Invariants

None. The benchmark harness is test infrastructure; its detectors and both pass bars are unit-tested in `tests/test_bench.py`.

## Consequences

- `bench/` gains task `t3_export`, condition F, the full run's bar as code (`decide_full`), `--bar` and `--resume`. The rough run's bar is untouched.
- SPEC §23 points here for the full run.
- Once accepted, the order is: T3 calibration, the main batch, the second model, then the write-up and the README with only the claims the numbers allow.

## Questions for the owner

1. **The pass bar and the claims table** (sections 3 to 5): accept as written?
2. **The second model:** Haiku 5.5 on A, C, D, E with 3 runs, or skip it, or a different model?
3. **The spend:** about $120 to $165 in total on the API key, with a stop after calibration and after the main batch?
