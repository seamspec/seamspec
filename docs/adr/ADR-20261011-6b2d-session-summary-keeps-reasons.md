---
id: ADR-20261011-6b2d
title: The session-start summary keeps each dead end's reason, shrinks in smaller steps, and may use 8,000 characters
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/adapters/claude.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-6b2d: The session-start summary keeps each dead end's reason, shrinks in smaller steps, and may use 8,000 characters

> Amends ADR-20261007-ac04 (decision 2, "size"). Everything else in that record stands.

## Context

Dogfooding finding #6 (2026-10-11). In the owner's project, a new session was asked, before it read any file, whether two approaches could be used. It answered correctly from the session-start summary that both were recorded dead ends, and added: *"I only have the truncated titles of these dead ends, so I can't tell you the recorded reason each one failed."*

Two causes, both in `session_summary()`:

1. **The shorter level dropped the reason.** When the full text didn't fit, a dead end became its id, the first 100 characters of what was tried, and its list of files. The heading above it still said *"don't retry unless the reason no longer applies"*. The reason is the one part that sentence needs.
2. **Real ledgers left the full level far sooner than assumed.** ADR-20261007-ac04 set 3,000 characters and was tested with short texts. In the owner's project a rule's text is about 230 characters and a dead end's reason about 450: 7 rules and 2 dead ends were already over, and 11 rules with 4 dead ends need about 7,500 characters.

A fact checked in the hooks reference on 2026-10-11: Claude Code caps each hook output string at **10,000 characters**. Over that, it saves the text to a file and gives the model the path and a preview of the first 2,000 characters, without asking it to read the file. That cliff is far worse than a shorter summary, so the limit must stay clearly below it.

## Decision

1. **The limit is 8,000 characters** (`SESSION_MAX_CHARS`), about 2,000 tokens once per session, with a margin under Claude Code's 10,000.
2. **A dead end keeps its reason at every level that lists it.** Shortened, it reads: id, the approach clipped to 120 characters, *"Why it failed:"* and the reason clipped to 200. Its file list is dropped instead; `get_constraints` has it.
3. **Detail shrinks in five steps, not three:**
   1. everything in full;
   2. rules in full, dead ends shortened;
   3. rule titles with at most two scope paths (*"+N more"*), dead ends shortened;
   4. rule titles alone, dead ends shortened;
   5. counts per area, then totals only.
   Rule texts go before dead-end reasons do: a rule's title is written to stand alone and its full text arrives with the first edit (`get_constraints`, the edit-time context), while a dead end without its reason can't be weighed at all.
4. The principles of ADR-20261007-ac04 stand: built from the ledger each time, nothing dropped silently, one line per record, only rules described as approved.

**Alternatives considered:**
- **Keep 3,000 characters and only add the reason.** The owner's 11 rules would then show as titles only in every session, which is what the "critical" marking planned for v0.2 is meant to avoid for the rules that matter most.
- **Use the whole 10,000.** No margin: one long rule would tip the summary over the cliff, and the model would get a 2,000-character preview.
- **Clip rule texts instead of dropping them.** A rule cut mid-sentence can say the opposite of what it means (*"never X unless…"*). A title is complete by design.
- **A config key for the limit.** Not yet: nobody has asked, and the hard ceiling is Claude Code's, not the user's.

## Enforced Invariants

To be proposed: "every dead end the session-start summary lists carries its reason", and "the summary never exceeds Claude Code's hook output limit".

## Consequences

* A project with around ten rules gets every rule and dead end in full at session start again.
* SPEC §16.1 and §19.10 are updated; ADR-20261007-ac04 points here for its size decision.
* The v0.2 "critical" marking is still wanted for large ledgers, where rule texts are the first thing to go.
