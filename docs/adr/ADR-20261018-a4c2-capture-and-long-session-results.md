---
id: ADR-20261018-a4c2
title: "Results: capture passes, the long session showed no slip"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-18
scopes: ["docs/benchmark/", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261018-a4c2: Results of the capture and long-session benchmarks

## Context

The owner ran both counted batches on 2026-10-18, under the plan and pass bars of ADR-20261015-c8e1, after calibration found and fixed three product problems (ADR-20261018-6e1a, ADR-20261018-0b7d) and two harness problems (PR #80; cost counting in ADR-20261018-6e1a). The write-ups are [`capture-1.md`](../benchmark/capture-1.md) and [`long-1.md`](../benchmark/long-1.md).

## Decision: the results, and what may be said

**Capture (`capture-1`): PASS, on all three conditions of the bar.** 30 runs, $12.69.
- **Broken agreements:** SeamSpec (empty ledger, agreements only said in chat) **0**, an agent keeping its own notes **8**, nothing **22** (`full-1`), notes written by a person **0** (`full-1`).
- **Captured:** SeamSpec captured 39 of 40 rules as locked tests that catch their agreement's violating patch, plus 15 of 15 dead ends.
- **Why the notes lost:** in T2, the notes-keeping agent wrote both agreements down every time, then broke them in 4 of 5 runs when later requests conflicted. It rewrote its own notes to match the request ("half-up replaces banker's rounding"), sometimes after asking, sometimes not. SeamSpec's agent changed nothing and filed supersede requests for a person to decide.

**Long session (`long-1`): no slip to catch.** 27 runs, $18.29. Every condition (nothing, hand-written notes, SeamSpec) broke 0 agreements in one 21-prompt session, and nothing was compacted.

**Claims across all benchmarks:**

| Claim | Status | Source |
|---|---|---|
| SeamSpec at least halves broken agreements against no help | **Yes** | `full-1`, `capture-1` |
| With plain tests the agent rewrites them; SeamSpec's stay as approved | **Yes** | `full-1` |
| Fewer broken agreements than plain tests with a Stop hook | **Yes** | `full-1` |
| **SeamSpec turns agreements only said in chat into approved, enforced rules** | **Yes** | `capture-1` |
| **Fewer broken agreements than an agent keeping its own notes** | **Yes** | `capture-1` |
| Fewer broken agreements than the same rules written in CLAUDE.md by a person | No (tie) | `full-1` |
| Fewer than ADRs; enforced better than advisory; better with ~40 rules than notes | No | `full-1` |
| In a long session, the checks catch what the agent forgets | No (no slip) | `long-1` |

**May also be said, as findings:**
- agreements are lost **between sessions**, not within a long one;
- with notes, the **agent** decides when an agreement gives way to a new request, while with SeamSpec a person does (supersede).

**Positioning that follows:** not "your agent remembers better". It's this: *rules you never wrote, captured from what you said, proven by a test the agent can't quietly rewrite, and changed only with your approval.* The owner's line from the discussion: *"Your agent can't quietly renegotiate what your team agreed."*

## Alternatives considered

- **Lengthen the long session until something slips** (more requests, forced compaction): that would change the pre-set plan after seeing the result. If wanted, it's a new plan with its own bar.
- **Claim "beats notes" without qualifying which notes:** the person-written notes tie. The claim is only made against notes the agent keeps itself.

## Enforced Invariants

None.

## Consequences

- SPEC §23 records both results; §24's messaging and write-up use the claims above.
- **Next (agreed with the owner):** a "second actor" benchmark. A different agent session, or a scripted teammate edit, that doesn't read the notes makes the tempting change, testing whether anything stops it. Plan and pass bar first, then the owner's OK on spend.
- **Total spent on these two benchmarks,** calibration included: about $33.40, against the $125-160 approved.
