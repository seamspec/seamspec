---
id: ADR-20261013-e2b6
title: "Full benchmark result: pass; what we claim, and what we don't"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["docs/benchmark/full-1.md", "docs/SPEC.md", "README.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-e2b6: Full benchmark result: pass; what we claim, and what we don't

## Context

The full benchmark ran on 2026-10-13 under the plan and pass bar of ADR-20261013-9d41: 120 runs on Claude Sonnet 5.5 (3 tasks × 8 conditions × 5 runs), $111.94. Numbers, tables and caveats are in [`docs/benchmark/full-1.md`](../benchmark/full-1.md).

| Condition | Rules broken (15 runs) | Rule tests changed | Dead end repeated |
|---|---|---|---|
| A · nothing | 22 | 0 | 6 |
| B · SeamSpec advisory | 0 | 0 | 0 |
| C · SeamSpec enforced | 0 | 0 | 0 |
| D · plain tests + Stop hook | 10 | 12 | 5 |
| E · rules as notes in `CLAUDE.md` | 0 | 0 | 0 |
| F · decisions as ADRs only | 7 | 0 | 1 |
| G · notes, 36 more rules | 0 | 0 | 0 |
| H · SeamSpec enforced, 36 more rules | 0 | 0 | 0 |

**Verdict by the pre-set bar: PASS.** C at most half of A (0 against 22), no worse on any task, C beats D by the margin on all three measures, and C's median cost is 1.17× A's.

## Decision

### 1. The result stands as it is

It is recorded with the claims the plan allows, and no others.

| Claim | Allowed |
|---|---|
| SeamSpec at least halves broken agreements, against no SeamSpec | Yes |
| With plain tests the agent rewrites them; SeamSpec's rule tests stay as approved | Yes |
| Fewer broken agreements than plain tests with a Stop hook | Yes |
| Enforced mode breaks fewer agreements than advisory mode | **No** |
| Fewer broken agreements than the same rules written in `CLAUDE.md` | **No** |
| The same, with about 40 rules | **No** |
| Fewer broken agreements than the same decisions kept as ADRs | **No** ("unclear": a gap of 7, the bar is 8) |

### 2. What the run showed that the pass bar doesn't say

- **A well-kept notes file remembers as well as SeamSpec,** at 3 rules and at 39, for about a third less cost per run. The owner predicted this before the run; the many-rules conditions were added because of it, and they agree.
- **The gates never fired.** In 30 enforced runs the Stop gate blocked nothing and pre-commit refused nothing; the advisory condition, with no gates, also broke no rule. With this model, knowing the rule was enough. Enforcement is the part of SeamSpec we have built the most of and shown the least.
- **Plain tests fail in one specific way:** when a request contradicts a rule, the agent rewrites the test (every such run). Where no request contradicts a rule, plain tests held. And a test can't carry a dead end: the failed approach came back in every T1 run with plain tests.
- **ADRs were read and still overridden.** The agent opened the records in every F run, yet broke 7 rules, sometimes writing a new record to supersede the old one itself. Nothing told it to ask first, and nothing stopped it from editing the record.

### 3. Positioning

**SeamSpec is not pitched as a better memory.** It is pitched as what a notes file can't be:

1. **Rules you don't have to write.** The agent proposes each rule as the code lands; a human approves. The notes file that matched SeamSpec here was written by us, complete and correct, before the run. In a real project somebody has to write and maintain it.
2. **Each rule proven by a test** that runs on every commit, so a rule is true today, not just written down.
3. **Tests the agent can't quietly rewrite,** and a changed requirement goes through a human (the supersede flow).
4. **A human approval on record** for every rule.

Point 3 is measured (D against C). Points 2 and 4 are how the product works. **Point 1 is the owner's and the agent's shared judgment and one project's experience; it is not measured yet** (section 4).

**Not said anywhere** (README, site, launch post), until measured:
- that SeamSpec remembers rules better than a notes file or ADRs;
- that enforced mode beats advisory mode;
- that agents forget rules as the context fills, or that "the gate catches what the agent forgets". Plausible, and the reason the gates exist; this run produced no slip for them to catch.

The planned write-up title *"Enforcing AI Coding Invariants with Hooks, Not Hope"* (SPEC §24.4) is dropped: it names the one thing the run did not show.

### 4. What gets measured next

Two follow-up tests, to be planned with their own pass bar before any run:

- **Capture:** a project that starts with no rules written anywhere; the agreements are only said in conversation in session 1. Compare an agent told to keep its own notes with SeamSpec's capture (propose, approve). Do rules nobody wrote by hand survive to session 3? Asked for by the owner on 2026-10-13.
- **A long session:** the tempting request arrives after a lot of unrelated work in one session. This is the direct test of "the gate catches what the agent forgets".

### 5. The second model (reported, not judged)

Haiku 5.5 on A, C, D and E, 36 runs, $3.11 ([`full-1-haiku.md`](../benchmark/full-1-haiku.md)). Rules broken in 9 runs each: **A 13, C 0, D 9, E 0**; rule tests changed: D 15, others 0.

- The question was whether enforcement matters more with a less careful model. **On these tasks it doesn't:** the notes file again matched SeamSpec, and the gates again never fired.
- **Plain tests did worse than with Sonnet:** more rewritten tests, and rules broken in a task where Sonnet had kept them.

So the weaker model strengthens the two claims about plain tests and leaves everything in section 3 as it is. "The gate catches what the agent forgets" still has no evidence; the long-session test is where it could get some.

**Alternatives considered:**
- **Lead with enforcement anyway** ("it would matter with a weaker model"). Not without data. The second model and the long-session test are how that claim gets earned.
- **Drop E, G and their result from the write-up.** They are the most useful thing the run found, and the first objection any reader raises. Publishing them is what makes the three allowed claims believable.
- **Call F "worse than SeamSpec".** The pre-set rule says "unclear" at a gap of 7. It stays "unclear".

## Enforced Invariants

None.

## Consequences

- SPEC §23 records the result; §24 and §25 change as in section 3; the README (not yet written) follows this record.
- Both models agree, so the positioning does not depend on which one a user runs.
- The capture and long-session tests join the plan before launch (ADR-20261013-f4a8 orders the remaining v0.1 work).
- B ≈ C and E ≈ C, first seen in the rough run (ADR-20261006-b270) and the quick E run (ADR-20261007-e1a7), are now confirmed at five runs per cell on three tasks.
