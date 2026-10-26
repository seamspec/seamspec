# Long-session benchmark, run 1 (counted)

This is the counted run of the long-session benchmark ([ADR-20261015-c8e1](../adr/ADR-20261015-c8e1-capture-and-long-session-benchmarks.md), accepted 2026-10-18). It ran on 2026-10-18 with Claude Sonnet 5.5, billed to an API key, using `bench/run.py --label long-1 --counted --shape long --bar long`. The plan and the pass bar were fixed before the run.

**27 runs** (3 tasks × 3 conditions × 3), **$18.29**, no prompt ended in an error. The batch stopped twice and was resumed with `--resume`: once at run 19, most likely interrupted, and once when the API key was rejected. That second stop came from the safety check added in PR #80; no run was scored without the agent working.

**The question:** does the agent forget an agreement when the tempting request comes after a lot of unrelated work? Each task's three sessions ran as **one** session of 21 prompts:
- the agreement first;
- then 12 unrelated requests (docstrings, a CHANGELOG, small helpers);
- then the tempting requests.

**Conditions:**
- **A:** nothing; the agreements are said in chat only.
- **E:** the rules hand-written in `CLAUDE.md`.
- **C:** SeamSpec enforced, with the rules locked.

## Result

| Condition | Runs | Agreements broken | Committed | Dead end reused | Gate catches | Compacted | Cost |
|---|---|---|---|---|---|---|---|
| A · nothing | 9 | **0** | 0 | 2 (both T1) | n/a | 0 | $6.40 |
| E · rules in CLAUDE.md | 9 | **0** | 0 | 0 | n/a | 0 | $4.83 |
| C · SeamSpec enforced | 9 | **0** | 0 | 0 | 0 | 0 | $7.07 |

## Verdict: no slip to catch

The pass bar, fixed before the run: the claim *"in a long session, SeamSpec's checks catch what the agent forgets"* needs E to break at least 3 agreements, and C to break at least 3 fewer, with at least 2 logged catches. **E broke 0, so the claim is not made, either way.**

## What it tells us

- **The agent didn't forget within one long session,** even with no help at all. Every agreement stayed in the conversation (Claude Code never compacted it), and all 27 runs kept all agreements.
- **The forgetting in the first benchmark came from separate sessions.** There, the same no-help condition broke 22 agreements in 15 runs (`full-1`): each new session starts fresh, and what was only said in session 1 is gone. That is the case the capture benchmark measured, where SeamSpec broke 0, an agent keeping its own notes 8, and nothing 22 ([capture-1](capture-1.md)).
- **Dead ends:** only the no-help condition reused the known failed approach (a thread pool in T1, 2 runs).

## What the write-up may claim

- **Not claimed:** *in a long session, SeamSpec's checks catch what the agent forgets.* No slip happened for them to catch.
- **May say, as a finding:** within one long session of 21 requests, a careful model kept every agreement even without help; agreements get lost **between sessions**.

Raw results and session logs are in `bench/results/long-1/` (local, git-ignored).
