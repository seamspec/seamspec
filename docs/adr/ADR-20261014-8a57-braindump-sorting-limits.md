---
id: ADR-20261014-8a57
title: "BRAINDUMP sorting: decisions count toward the review cap, reject the rest at once, offer again when the code changes"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-14
scopes: ["seamspec/core/lifecycle.py", "seamspec/review.py", "seamspec/core/braindump.py", "seamspec/templates/commands/drain.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261014-8a57: BRAINDUMP sorting limits

## Context

From the owner's Antigravity hands-on test (2026-10-14, also ADR-20261014-6c2d):

1. **A pile of decisions.** A long implementation plan pasted into BRAINDUMP.md became 20 proposed decisions in one sort. The 3-per-sort limit covered rules only, and `proposals.max_pending` counted proposed rules only, so nothing stopped it.
2. **No quick way out.** Clearing that pile meant rejecting 19 decisions one by one in `seamspec review`.
3. **The offer went unanswered.** The session-start offer to sort notes fired in a chat whose first message was a task ("write cart.py…"). The agent did the task, the offer was used up, and the next chat stayed quiet because the notes hadn't changed, although the code those notes waited for now existed.
4. **Labels:** the owner called the decision they approved a "rule". Review already shows it under "== Proposed decisions (no test of their own…)" with a "Proposed decision n of m" header, so no change was needed there.

## Decision

1. **Decisions count toward the review cap.** `lifecycle.pending_count` is the review backlog: `PROPOSED` rules plus proposed decisions with no rule of their own. `propose_decision` returns `queue_full` at `proposals.max_pending` and writes nothing, as `propose_invariant` already did. The drain steps say "at most 3 rules and decisions together in one sort", and say to stop and ask for a review on `queue_full`.
2. **"Reject the rest" in review.** While more than one proposed decision is left, the prompt adds `[x] reject this and the N after it`. Review lists the ones it would reject and asks *"Reject all N?"* (default no). Rules keep one-by-one review: each rejection can record a dead end, which needs its own answer.
3. **Offer again when the code changes.** `nudge.json` also remembers the project's files at the last offer (`tree.tree_fingerprint`: `HEAD` plus changed and untracked, non-ignored files; BRAINDUMP.md is git-ignored, so it doesn't count). The offer comes back when the pending notes or the code changed. A "no" still holds for the same notes and the same code.

**Alternatives considered:**
- **A separate cap for decisions:** two numbers to explain, for one human's review time.
- **"Reject all" for rules too:** a rejected rule can become a dead end with its own reason, so a bulk answer would either lose that or ask N questions anyway.
- **Re-offer every session while notes wait, or after a time:** it nags a person who said no to the same notes and code; a change in the code is the moment the answer can differ.

## Enforced Invariants

None yet.

## Consequences

- A project can hold at most `max_pending` (10) items awaiting review in total; a big plan drains over several sorts and reviews instead of one flood.
- An agent that writes code in a project with unsorted notes will see the offer again in its next session. Turn it off with `braindump.nudge = "off"`.
- Planned rules (notes whose code doesn't exist yet) are the next change; with them, notes that wait for code stop being "pending" at all.
