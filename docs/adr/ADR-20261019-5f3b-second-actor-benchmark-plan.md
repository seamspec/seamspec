---
id: ADR-20261019-5f3b
title: "Plan and pass bar for the second-actor benchmark"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-19
scopes: ["bench/"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261019-5f3b: Plan and pass bar for the second-actor benchmark

## Context

The benchmarks so far ran **one** agent through a task (ADR-20261018-a4c2):
- Notes a person wrote carefully **tie** with SeamSpec on a careful model.
- An agent keeping its own notes loses (8 broken against SeamSpec's 0).
- Within one long session, nothing slipped.

The case notes can't cover is **someone else changing the code**: a teammate, their agent, or another tool. A note only helps if whoever changes the code reads it and obeys it; SeamSpec's rules are tests that CI runs on every change. The owner asked for this test on 2026-10-18.

**What is decided by construction, and what is measured.**
- **Decided by construction:** if a teammate edits the code by hand and pushes, a notes file can't stop it, and SeamSpec's CI check fails the build whenever a locked rule breaks. This is a **demonstration**: it shows what each setup enforces, and costs nothing (no model). It is reported as such, never as a measured advantage.
- **Measured:** what **a teammate's agent** does in a fresh clone, without the original conversation, when asked for the tempting changes; and whether what it breaks would reach `main`.

## Decision

### The scenario

1. **Session 1, the original author.** As in `capture-1`, for each setup:
   - the author's agent hears the agreements in chat and does the first task;
   - in S, the scripted reviewer approves its rules;
   - everything is committed and pushed to a shared bare repository ("origin").
2. **The teammate.** A fresh `git clone` of origin, the way a teammate starts. A clone carries only committed files: the notes, the `CLAUDE.md` block, the ledger and the CI workflow. It does **not** carry `.git/hooks`, `.seamspec/.local` (consent, trust), or the author's local plugin install. The teammate has the `seamspec` command installed but **hasn't run `seamspec init`**, so SeamSpec's hooks don't run in their agent; only what the repository carries does.
3. **The teammate's agent** is a fresh Claude Code session in that clone. It gets only the tempting requests: sessions 2 and 3, as one session, never restating the agreements. Then the teammate pushes.
4. **CI on the push.** Each setup's own check runs on what was pushed:
   - the project's existing tests, for every setup;
   - plus `seamspec verify --all --ci` for SeamSpec, exactly as SeamSpec's CI workflow runs it.

   A push whose CI fails is **blocked**, as branch protection would block its merge.

### Conditions (same three tasks, same prompts)

| | Session 1 setup | What the teammate's clone carries |
|---|---|---|
| **A** | nothing | the code |
| **E** | the rules hand-written in `CLAUDE.md` (as `full-1`) | the code and `CLAUDE.md` |
| **N** | the author's agent keeps NOTES.md (as `capture-1`) | the code, NOTES.md and the `CLAUDE.md` line |
| **S** | SeamSpec capture with an empty ledger and the scripted reviewer (as `capture-1`) | the code, the ledger, the protocol block and the CI workflow |

### The human edit (the demonstration, no model)

For every task and setup, a scripted teammate commits each agreement's **violating patch** (`task.json` → `capture.mutants`) on top of session 1's result and pushes. CI runs as above. This is reported in its own table, labelled as a demonstration.

### Measured

- **Broken by the teammate's agent:** the hidden oracle on the teammate's pushed `HEAD`.
- **Landed:** broken *and* CI passed. This is the headline number: agreements that reach `main`.
- Whether the teammate's agent **asked** before changing an agreement (a supersede request, or a question to the user), read from its final messages. Reported only.

### Pass bar (fixed before any run)

1. **Something to stop:** at least 3 agreements broken by the teammate's agent across E and N together. If fewer, the teammate's agent didn't break enough to test any gate, and the claim below is not made either way.
2. **The claim *"With SeamSpec, a broken agreement doesn't reach `main`, whoever made the change"*** needs:
   - **landed = 0 for S**, across the agent runs and the human edits;
   - **landed ≥ 3 for E and N together**, across the agent runs.
3. **The teammate's agent breaks fewer with SeamSpec,** read with the full run's rule (`read_against_c`) on S against E and against N. This is reported, and becomes a claim only where it reads "worse" for the other setup.

### Runs and cost (Sonnet 5.5, API key, run by the owner)

- **Runs:** 4 conditions × 3 tasks × 3 runs = **36 runs**.
- **Cost per run:** session 1 (about $0.15-0.20; plus the review for S) and the teammate's session (about $0.25-0.35), so about **$0.45-0.55**.
- **Total: about $16-20,** plus a 2-run calibration (about $1).
- **The human edits:** no model, $0, run by the harness in tests and in the batch.
- **Order:** the harness comes first, in its own PR with tests and no paid run, as before.

## Questions for the owner (answered 2026-10-19)

1. **The teammate:** has the `seamspec` command but hasn't run `seamspec init`, so there are no local hooks, only what the repository carries, with CI as the gate. Is that the right teammate? Alternatives:
   - **a teammate with no SeamSpec at all:** the outcome is the same for CI, and their agent can't run `seamspec context`;
   - **one who ran `init`:** that's just `capture-1` again.
2. **The pass bar** above, including that the human-edit table is labelled a demonstration and never counted as measured.
3. **About $16-20 spend**, your key, your terminal.

**The owner's answers (2026-10-19): yes to all three.** The owner also asked whether CI needs GitHub billing fixed. It doesn't: "origin" is a local bare repository, and "CI" is the same command run locally on what was pushed.

## Clarifications made while building the harness (before any run)

These change no threshold.

- **Some violations are caught by a project's own tests.** T1's own test suite catches the signature break ("`enqueue` returns a dict"); none of the other seven violating patches is caught by its task's own tests. So in the demonstration that edit is blocked in **every** setup, and the write-up says so.
- **The author's push** commits whatever session 1 left, with the commit check skipped. It's harness bookkeeping, not the agent's own commit.
- **The teammate pushes only what their agent committed.** Uncommitted work stays on their machine, as it would.
- **The teammate has `seamspec` on their PATH** (answer 1), so their agent can run `seamspec context` if the protocol block in `CLAUDE.md` leads it there. Their clone has no hooks, no `.seamspec/.local` and no plugin, and the tests check all three.
- **The demonstration runs on every run,** on that run's session-1 result, because S's captured rules differ from run to run. A patch that no longer matches the code session 1 left is recorded as "n/a", not as landed or blocked.

## Enforced Invariants

None.

## Consequences

- **If it passes,** the README can say SeamSpec stops a broken agreement from reaching `main` whoever made the change, which a notes file can't, with the human-edit table showing why.
- **If the teammate's agent breaks nothing in E and N,** we report that careful agents respect committed notes too, and lean on the demonstration and on CI as the reason teams need SeamSpec, without a measured claim.
- **It relies on SeamSpec's CI workflow** (`seamspec verify --all --ci`). That's how a team would run it, but the README must say CI is where it protects a team.
