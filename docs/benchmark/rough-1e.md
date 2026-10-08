# Quick condition E: rules written in CLAUDE.md (`rough-1e`)

Run on 2026-10-07: 6 runs (both tasks × 3) of condition E, on Claude Sonnet 5.5 with an API key. **$4.84, no errors.** It is compared with the counted rough run `rough-1` (same tasks, prompts, model and harness) by `python -m bench.compare --base rough-1 --with rough-1e`. The design and the reading rule were fixed before running ([ADR-20261007-e1a7](../adr/ADR-20261007-e1a7-quick-condition-e.md)).

| Condition | Runs | Violations | Committed | Tampering | Dead ends | Median cost |
|---|---|---|---|---|---|---|
| A · baseline (no SeamSpec) | 6 | 9 | 9 | 0 | 4 | $0.95 |
| B · SeamSpec advisory | 6 | 1 | 0 | 0 | 0 | $1.20 |
| C · SeamSpec enforced | 6 | 2 | 0 | 0 | 0 | $1.22 |
| D · plain tests + Stop hook | 6 | 6 | 6 | 6 | 4 | $1.14 |
| E · rules written in CLAUDE.md | 6 | 0 | 0 | 0 | 0 | $0.78 |

"Committed" counts violations in what was actually committed at `HEAD`; for `rough-1` it was measured from the cached working copies.

**Reading, by the rule fixed beforehand: notes match SeamSpec's memory.** V(E) = 0 ≤ V(C) + 1 = 3.

**From the logs:** in every T2 run, the notes-only agent refused both conflicting requests and asked the user, quoting the agreement from `CLAUDE.md`, for example *"I haven't changed anything, because this request conflicts with one of the team agreements in CLAUDE.md."* That's the same behavior SeamSpec's agent showed with `request_supersede`. It also cited the recorded `toFixed()` dead end.
