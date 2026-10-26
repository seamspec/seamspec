---
id: ADR-20261013-f4a8
title: "v0.1 after the benchmark: BRAINDUMP, critical rules, three more hosts, and an explainer for reviews"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["docs/SPEC.md", "docs/PROGRESS.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-f4a8: v0.1 after the benchmark: BRAINDUMP, critical rules, three more hosts, and an explainer for reviews

## Context

On 2026-10-05 v0.1 was cut down to the smallest version that could test the core loop: Claude Code only, no BRAINDUMP. The reason given was that the biggest risk was whether SeamSpec helps at all. The full benchmark has now answered that (ADR-20261013-e2b6): it passes, and it also shows that SeamSpec's case does not rest on remembering rules, which a well-kept notes file does as well. It rests on rules that get captured without anyone writing them, proven by tests, and approved by a person.

On 2026-10-13, with those numbers coming in, the owner decided what the first public release must contain. In the owner's words: the capture flow, where SeamSpec creates the rules as each phase is coded, keeps them from breaking, and proposes a superseding rule, "is a big WOW factor"; nobody writes those notes by hand consistently while building.

## Decision

**v0.1 grows.** These move from v0.2 (or are new) into v0.1, by the owner's decision:

1. **BRAINDUMP** (§13): the notes file a person jots into, drained by the agent into proposed rules, decisions and dead ends, with redaction and the session-start reminder. It is the other half of "you never write the list".
2. **The "critical" rule marking** (ADR-20261007-ac04): the few rules that always show in full to the agent. It changes the record format, so it is done before the first release.
3. **Three more hosts: Cursor, VS Code (Copilot) and Google Antigravity.** Antigravity is new to the plan.
   - The commit gate and CI already work with any tool, because they act in git. What is per host is getting the rules in front of the agent, offering SeamSpec's tools, and stopping the agent before it finishes.
   - **Level 1 for all three in v0.1:** the host's agent is shown the rules, can call SeamSpec's tools, and is blocked at commit and in CI. **Level 2** (stopped inside the session, as in Claude Code) where a host makes it straightforward.
   - Antigravity's extension points are read from its public documentation first (clean room). Each host needs a short hands-on check by the owner, as the chat dialogs did.
4. **An explainer for reviews** (new). The owner's idea: "a very protected agent with a tight system prompt" that explains to the user what the rule is and what changed, and the user decides. In dogfooding the owner did exactly this by pasting each review screen to a second agent. The shape, to be designed in its own ADR before it is built:
   - a **separate agent with fresh context**, not the one that wrote the code, shipped in the Claude Code plugin so SeamSpec's core still calls no model (§3);
   - **read-only:** it can read the rule, its test and the change; it cannot edit, run anything that changes state, or approve;
   - it explains **in chat, beside the review:** what the rule promises, what the test checks, what it doesn't cover, what changed, what looks off;
   - **the decision stays in SeamSpec's own review**, which goes on showing its own facts and the full test. The explainer's words never appear inside SeamSpec's cards or dialogs (locked rule `inv_aa498871`).
5. **Two more benchmark tests** before launch (ADR-20261013-e2b6, section 4): capture from conversation, and a long session.

> **What the owner decided and what is still a proposal.** Items 1 to 3 and 5, and the wish for item 4, are the owner's decisions of 2026-10-13. The two-level approach to hosts, the shape of the explainer, and the order below are the agent's proposals from the same conversation; the owner has not yet confirmed them, and each gets its own ADR before it is built.

**Order of the remaining v0.1 work (proposed):**

1. Write up the benchmark (this PR; the second model when it completes).
2. The explainer for reviews.
3. The "critical" marking.
4. BRAINDUMP.
5. Cursor, VS Code, Antigravity.
6. The capture and long-session tests, once BRAINDUMP exists, so capture is tested as shipped.
7. README, pitch and release work, with only the claims the numbers allow.

**Stays in v0.2:** the OpenSpec importer, more runner presets (jest, Go, Rust), the `npx` wrapper. A new candidate for v0.2, from the benchmark: propose rules from an existing notes file, one tested rule per line.

**Alternatives considered:**
- **Release the small v0.1 now and add these in v0.2.** The benchmark says the small v0.1's distinctive value against a notes file is thin without the capture side; the owner chose to launch with it.
- **Full host parity (level 2 everywhere) in v0.1.** Unknown effort per host, and the git-level gate already covers the hard stop.
- **Put the explanation inside `seamspec review`.** It would put a model's words where the approval is decided, and a model in SeamSpec's core.

## Enforced Invariants

None new. `inv_aa498871` (the agent never supplies approval dialog text) constrains item 4.

## Consequences

- The six-week plan of 2026-10-05 no longer describes v0.1. Rough estimate from here: explainer 2 to 3 days, critical marking 1 to 2, BRAINDUMP 3 to 5, three hosts 1 to 2 weeks (firmer after reading their docs), the two tests 2 to 3 days plus runs, README and release about a week: **roughly 4 to 5 weeks** to launch.
- SPEC §22 is updated; §13 (BRAINDUMP), §16.2 and §16.3 (hosts) stop being "v0.2" as each is built, each with its own ADR where the design changes.
- GitHub Actions for the organization has not run since #53 (billing); with more code coming, restoring CI and the Copilot review matters more.
