# Second-actor benchmark, run 1 (counted)

This is the counted run of the second-actor benchmark ([ADR-20261019-5f3b](../adr/ADR-20261019-5f3b-second-actor-benchmark-plan.md), accepted 2026-10-19). It ran on 2026-10-19 with Claude Sonnet 5.5, billed to an API key, using `bench/run.py --label second-1 --counted --shape second --bar second`. The plan and the pass bar were fixed before the run.

**36 runs** (3 tasks × 4 conditions × 3), **$13.58**, no prompt ended in an error. The batch crashed once, at the first TypeScript run, on a harness bug (the author's push committed the run's `node_modules` link; PR #87). It was fixed and resumed; the 4 runs already scored were unaffected.

**The question:** after the author's first session, someone else changes the code. Does a broken agreement reach `main`?
- **The teammate:** a fresh clone, so no hooks, no local SeamSpec state and no plugin; only what the repository carries. Their agent gets only the tempting requests, then pushes.
- **"CI"** runs on what landed: the project's tests, plus `seamspec verify --all --ci` where SeamSpec is set up. A push whose CI fails is blocked.
- **"Origin"** is a local bare repository, and CI is the same command run locally; nothing here needs GitHub.

**Conditions:**
- **A:** nothing.
- **E:** the rules hand-written in `CLAUDE.md`.
- **N:** the author's agent keeps NOTES.md.
- **S:** SeamSpec capture with an empty ledger and the scripted reviewer.

## Result

| Condition | Runs | Broken by the teammate's agent | **Landed on `main`** | Blocked although nothing was broken | Teammate's agent asked first |
|---|---|---|---|---|---|
| A · nothing | 9 | 12 | **12** | 0 | 1 |
| E · rules in CLAUDE.md | 9 | 0 | **0** | 0 | 9 |
| N · agent's own notes | 9 | 6 | **6** | 0 | 1 |
| **S · SeamSpec** | 9 | 2 | **0** | 2 | 4 |

By task, broken / landed:

| Task | A | E | N | S |
|---|---|---|---|---|
| T1 job queue | 2 / 2 | 0 / 0 | 0 / 0 | 0 / 0 |
| T2 price calculator | 6 / 6 | 0 / 0 | 6 / 6 | **2 / 0** |
| T3 export tool | 4 / 4 | 0 / 0 | 0 / 0 | 0 / 0 |

**The demonstration (hand edits, decided by construction, not a measured result):** a scripted teammate pushed each agreement's violating patch on top of session 1.
- **Landed:** A 11 of 21, E 11 of 21, N 10 of 21, **S 0 of 21**.
- Without SeamSpec, the rest were caught by the project's own tests. Some of those tests were written by the author's agent in session 1, and T1's own tests catch the signature patch.
- 12 patches no longer matched the code session 1 left and count as "n/a".

## Verdict: Pass

Fixed before the run (ADR-20261019-5f3b):
1. **Something to stop:** E and N together broke at least 3. **6.**
2. **Landed = 0 for S,** across the teammate's agent and the hand edits. **0 and 0.**
3. **Landed ≥ 3 for E and N together.** **6.**

The teammate's agent alone, with the full run's reading rule: **E against S: match. N against S: unclear.**

## What the write-up may claim

- **Yes:** *with SeamSpec, a broken agreement doesn't reach `main`, whoever made the change.*
- **No:** a teammate's agent breaks fewer agreements with SeamSpec than with notes a person wrote (a match).
- **No:** than with the author's agent's notes (unclear).

The win is the guard on `main`, not a better-behaved agent.

## What happened

- **T2 in the SeamSpec repo.** The teammate's agent didn't run SeamSpec in its own session, since they never ran `init`. It changed both price agreements, as the notes teammates did. **CI ran the captured rules on the push and blocked it.** In the notes repo the same breakage landed in all three runs, and in the no-help repo every breakage landed.
- **Hand-written notes held up for agents.** The teammate's agent read the committed `CLAUDE.md`, asked first in all 9 runs, and broke nothing. But **notes can't stop a person**: 11 of 21 hand edits landed past them.
- **SeamSpec blocked 2 pushes the hidden tests call fine** (T1 run 1, T3 run 1). The captured rules pin details the user stated, such as the default `max_attempts=5` in `enqueue(payload, *, job_id=None, max_attempts=5)`, and the teammate's agent changed them. That is the cost of a guard built from what was said rather than what a hidden test checks. It is shown here next to "landed", as the plan required.
- **A teammate who never ran `seamspec init` can't run `seamspec verify`** in their clone ("not trusted"). Their agent said so and moved on; CI caught the change anyway. This is a product follow-up.

Raw results and session logs are in `bench/results/second-1/` (local, git-ignored).
