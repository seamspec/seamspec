# Capture benchmark, run 1 (counted)

This is the counted run of the capture benchmark ([ADR-20261015-c8e1](../adr/ADR-20261015-c8e1-capture-and-long-session-benchmarks.md), accepted 2026-10-18). It ran on 2026-10-18 with Claude Sonnet 5.5, billed to an API key, using `bench/run.py --label capture-1 --counted --bar capture --baseline full-1`. The plan, the scoring and the pass bar were fixed before the run. Four calibration runs came first and found three problems, all fixed before counting (ADR-20261018-6e1a, ADR-20261018-0b7d).

**30 runs** (3 tasks × 2 conditions × 5), **$12.69**, no prompt ended in an error.

**The question:** agreements are only *said* in session 1's chat; nobody writes them down. Do they still hold after sessions 2 and 3, which ask for changes that conflict with them? Two conditions ran:
- **N, the agent keeps its own notes:** one `CLAUDE.md` line asks it to write agreements into NOTES.md and read it each session.
- **S, SeamSpec with an empty ledger:** between sessions a scripted person approves every proposed rule whose test passes.

The two other cells come from `full-1`, which used the same prompts:
- **A:** nothing, agreements said in chat only;
- **E:** a person wrote every rule in `CLAUDE.md`.

## Result

| Condition | Runs | Agreements broken | Per run | Median cost |
|---|---|---|---|---|
| A · nothing (from `full-1`) | 15 | 22 | 1.47 | |
| **N · agent keeps its own notes** | 15 | **8** | 0.53 | $0.46 |
| **S · SeamSpec capture (empty ledger)** | 15 | **0** | 0.00 | $0.48 |
| E · rules hand-written in CLAUDE.md (from `full-1`) | 15 | 0 | 0.00 | |

By task (broken agreements):

| Task | A | E | N | S |
|---|---|---|---|---|
| T1 job queue (3 rules) | 4 | 0 | 0 | 0 |
| T2 price calculator (2 rules) | 10 | 0 | **8** | 0 |
| T3 export tool (3 rules) | 8 | 0 | 0 | 0 |

**Capture:** after session 1 and the review, SeamSpec held **39 of 40 rules** as locked tests that pass on the starting code and fail on that agreement's violating patch, plus **15 of 15 dead ends**. The one miss: T1 run 2 didn't capture "jobs are processed at most once". Every run captured at least two-thirds of its agreements.

## Verdict: Pass

Fixed before the run (ADR-20261015-c8e1):
1. **Capture rate:** at least two-thirds of a run's agreements in at least 4 of 5 runs of each task. **Met: 5 of 5 for every task.**
2. **At most half of A:** S broke 0 against A's 22. **Met.**
3. **No worse than N:** S broke 0 against N's 8. **Met.**

N against S, using the full run's reading rule: **N is clearly worse than S.**

## What the write-up may claim

- **Yes:** *SeamSpec turns agreements only said in chat into approved, enforced rules.*
- **Yes:** *Fewer broken agreements than an agent keeping its own notes.*
- **Still no** (unchanged from `full-1`): fewer broken agreements than the same rules carefully written in `CLAUDE.md` by a person. E and S both broke 0.

## What happened

**T2 is where notes and SeamSpec part ways.**
- **The notes-keeping agent wrote both agreements** (banker's rounding; totals never negative) into its NOTES.md in **every** run.
- **Then it broke them anyway in 4 of 5 runs,** when session 2 asked for vouchers that refund the difference and session 3 asked to match a payment provider's half-up rounding. It **rewrote its own notes to match**. Run 1's NOTES.md ends the batch saying totals are rounded *"halves rounded up … (changed from banker's rounding …)"*, with a new *"Exception (marketing prepaid vouchers)"* that allows a negative total. The agreement was overwritten, and nobody approved the change.
- **With SeamSpec,** the same requests hit locked rules with tests. The agent changed nothing and filed a **supersede request** for a person to decide, e.g. *"I haven't changed `totalCents` … The change conflicts with a locked rule that a human has to approve changing … I filed a supersede request instead"*. It broke nothing. The scripted reviewer declined every request, since these tasks never agree to change an agreement.

**T1 and T3:** both conditions kept every agreement. A careful model keeps agreements it wrote down when nothing later asks it to break them hard.

**Dead ends:** the task's own detector flagged the known failed approach in **5 S runs and 2 N runs**, all in T1. In the S runs, the agent read the recorded dead end, a thread-per-job pool that deadlocked, and built a different worker pool around its causes (no shared lock held while jobs run, no job running twice). The detector, fixed before the first benchmark, flags any thread pool, so these count as reappearances as defined.

## How it was measured

- **Violations:** hidden oracle tests on the final working tree, as in `full-1`. Committed violations at `HEAD` were the same (S 0, N 8).
- **Captured:** the run's locked rule tests run on a copy of the task's starting code, as it is and once per agreement with that agreement broken. A test captures an agreement if it passes on the start and fails on the break. Tests of code added later fail on the start and never count. Each violating patch is checked, in `tests/test_bench_capture.py`, to break exactly its own agreement against the hidden tests.
- **The reviewer** is a script, as the owner agreed: it approves every proposed rule whose test passes and declines every supersede request (these tasks never agree to change an agreement). A person might reject a weak rule; the script doesn't.

## Calibration, before counting

Four calibration runs on T1 (about $2.20 in all), recorded in ADR-20261015-c8e1:
1. **A rejected API key.** The harness now stops on it (PR #80).
2. **No capture: the protocol only asked about behaviour the agent builds.** The agent understood the agreements but proposed nothing. Fixed: SeamSpec's protocol now says to capture what the user states (ADR-20261018-6e1a).
3. **No capture: the rule tests couldn't import the code.** All three agreements were proposed, but SeamSpec's own pytest config dropped the project's `pythonpath = ["src"]`. Fixed for every project set up that way (ADR-20261018-0b7d).
4. **4 of 4 captured** (three rules plus the dead end), 0 broken.

The cost counter was also corrected before counting: Claude Code reports running totals (ADR-20261018-6e1a).

Raw results and session logs are in `bench/results/capture-1/` (local, git-ignored).
