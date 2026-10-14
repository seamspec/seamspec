---
id: ADR-20261013-d9e4
title: "BRAINDUMP in v0.1, as designed in §13, with five changes"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/core/braindump.py", "seamspec/core/lifecycle.py", "seamspec/mcp_server.py", "seamspec/cli.py", "seamspec/review.py", "seamspec/installers/scaffold.py", "seamspec/adapters/claude.py", "seamspec/templates/BRAINDUMP.md", "seamspec/templates/commands/drain.md", "seamspec/templates/directive.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-d9e4: BRAINDUMP in v0.1, as designed in §13, with five changes

## Context

BRAINDUMP was cut from v0.1 on 2026-10-05 to keep the first version small. The full benchmark (ADR-20261013-e2b6) then showed that SeamSpec's case against a notes file is not memory but who writes the list: SeamSpec builds it from the work. The owner moved BRAINDUMP into v0.1 (ADR-20261013-f4a8): it is the other half of "you never write the list", the person's own scratchpad sorted by the agent into proposals they then approve.

SPEC §13 already designed it: ownership (the person owns the text above the marker), parsing rules, the agent's classification, the managed section, redaction, and the session-start nudge. Until now the protocol pointed agents at "a section of the plan" instead (ADR-20261011-0995).

## Decision

Build §13 as designed: `core/braindump.py` (parse, state, dismiss, tidy, nudge), the `braindump_pending` and `propose_decision` tools, `origin_ref` on dead ends, the `/seamspec:drain` command, `seamspec drain [--json] [--tidy]` and `seamspec propose-decision`, the session-start nudge, and protocol rule 6 (the user's notes: never edit them; sort them on request; ask once when new notes appear). Records made from a note carry its id (`origin.ref` / `origin_ref`) and mark it sorted. Nothing from a sort is ever locked without a person's approval.

Five changes from the design:

1. **`init` creates the file**, once, with its examples **inside an HTML comment**, so they are never read as notes. It adds the file to `.gitignore` only when it creates it. A team that shares the file removes that line, and a rerun never adds it back (§13.3 says teams may share it; adding the line on every run would undo that).
2. **`braindump_pending(dismiss=…)` takes a mapping** (`{"bd_…": "todo"}`) instead of a list of objects, which keeps the tool's definition small.
3. **Proposed decisions are reviewed.** `propose_decision` creates a PROPOSED decision record with no rule of its own; `seamspec review` now has a "Proposed decisions" section (accept / reject / skip), journaled as `decision_accepted` / `decision_rejected`. Accepting records the decision; it enforces nothing. A decision linked to rules still follows them.
4. **Dead-end approaches are redacted too,** not only failure reasons, since notes often hold pasted commands with secrets in them.
5. **The nudge runs on `startup` and `clear` only,** never after `compact`, so it never interrupts a task in progress. It is silent on any error, and `braindump.nudge = "off"` turns it off.

**Tool definitions:** nine tools now. The two new ones would have taken the definitions over the 1,500-token budget the tests enforce, so every tool drops its generic output schema (results stay JSON text, which is what clients read); the nine come to about 1,485 tokens.

**Alternatives considered:**
- **Keep BRAINDUMP in v0.2, and keep pointing agents at a plan section.** It works for people who write plans; BRAINDUMP is for the many who don't.
- **Parse and classify in SeamSpec.** Classification needs judgment, and SeamSpec's core calls no model (§3); the in-session agent classifies, SeamSpec stores.
- **Let the agent tidy the file.** The text is the person's; only `seamspec drain --tidy`, run by them, changes it.
- **Raise the token budget.** Dropping a schema nobody reads costs nothing; raising the budget costs every session.

## Enforced Invariants

To be proposed: "a sort never changes the person's part of BRAINDUMP.md", and "a note becomes nothing locked without a person's approval".

## Consequences

- New projects get `BRAINDUMP.md` and a `[braindump]` section in their config. Existing projects get the file on their next `seamspec init`.
- The protocol has a new rule 6 and renumbers the rest; existing projects see a `doctor` note until they rerun `init`, which keeps any line a user wrote inside the block.
- The chat review (`open_review`, off by default) doesn't show proposed decisions; `seamspec review` does.
- Not yet tried in a real session: the first sort of a real scratchpad is the owner's.
