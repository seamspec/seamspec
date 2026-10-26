---
id: ADR-20261014-5e3a
title: "Planned rules: notes whose code doesn't exist yet steer the agent until they can be proposed"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-14
scopes: ["seamspec/core/braindump.py", "seamspec/adapters/claude.py", "seamspec/mcp_server.py", "seamspec/cli.py", "seamspec/templates/commands/drain.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261014-5e3a: Planned rules

## Context

In the owner's Antigravity test, five rule-like notes were sorted before `cart.py` existed. The drain correctly proposed none of them: a SeamSpec rule is a sentence plus a test that passes now, and review shows the test failing without the change. But the notes then sat in BRAINDUMP.md doing nothing. Nothing told the agent about them while it built the cart, which happened to match them only by luck. The owner expected the notes to count from the moment they were sorted ("I expected 6 rules for review"). We agreed on a middle way: notes count right away, but only as guidance, and nothing is enforced before a human approves a passing test.

## Decision

1. **A new way to set a note aside: `planned`**, next to `todo` and `exploration` (`braindump_pending(dismiss={id: "planned"})`, `seamspec drain --dismiss ID=planned`). The drain uses it for a constraint whose code doesn't exist yet. The note stays in the file and stops being pending.
2. **The agent sees planned rules, labelled as not enforced:**
   - in the session-start text, after the rules in force (*"rules the user planned in their notes (not enforced, no test yet). Build to them. When the code for one exists and works, propose it as a rule…"*; at most 15, then a count);
   - in `get_constraints` (`planned`, project-wide, since a note has no scope);
   - in `braindump_pending`, `seamspec context`, `seamspec drain` and `seamspec status`.
3. **They become rules the usual way.** Once the code works, the agent proposes the rule with `origin_ref` = the note id, and the note becomes `invariant`. Each sort also looks at planned notes. Review and approval are unchanged.
4. **Personal, like BRAINDUMP.md.** The plan lives in `.seamspec/.local/braindump.json`, never in the committed ledger. Deleting the note drops it, and `drain --tidy` leaves planned notes in the person's part. The text recorded for a note that becomes a record is now looked up among all notes in the file, not only pending ones, so a planned note keeps its own words.

**Alternatives considered:**
- **A `PLANNED` status on invariants in the ledger:** a schema change touching the journal, `doctor`'s forward-only checks and CI, for something that is a personal intention with no test. It also blurs "the ledger holds what a human approved".
- **A new MCP tool (`plan_rule`):** the nine tools sit at about 1,485 of the 1,500-token budget. One more value in `dismiss` costs a few tokens.
- **Proposing a rule with a placeholder or failing test:** review would show something that can't be approved, and it would weaken the meaning of a proposal.

## Enforced Invariants

None yet.

## Consequences

- Notes steer the code from the moment they are sorted. That's the "plan first, rules appear as code lands" flow the capture test will measure.
- **Planned rules are not shared with a team**, the same as BRAINDUMP.md, which is git-ignored by default. A team that wants shared intentions keeps them in a committed plan; the protocol already says to propose those when their code works.
- **The session-start text grows by up to 15 lines.** It is separate from the rules summary and its size limit, so planned notes never push approved rules out.
