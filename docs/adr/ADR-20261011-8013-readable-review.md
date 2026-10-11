---
id: ADR-20261011-8013
title: A readable review - summary first, the test's checks pulled out, the full test still shown
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/review.py", "seamspec/chat_review.py", "seamspec/templates/commands/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-8013: A readable review - summary first, the test's checks pulled out, the full test still shown

> **Status: ACCEPTED** as a plan (the owner said yes on 2026-10-11). Nothing is built yet. It is built together with the dogfooding fixes, red-green first.

## Context

Dogfooding on a real project (2026-10-10) showed what `seamspec review` feels like in practice: a rule's id and text, then 40 to 60 lines of test code in one scroll, then a question. The owner's words: *"many lines of code dumped in front of the user"*. Three observations from those sessions:

- The owner could judge a rule quickly only after someone pointed out **what the test checks** (for the cache rule: the second run sent nothing, every answer came from the cache, and nothing was sent after a restart).
- The most useful help all week came from the agent, unprompted: *"the rule names four decisions, but the test only checks two"*. Both gaps it named were real, and the tests were strengthened before approval.
- The red-green line was wrong in that project (a separate bug), so the one line that is supposed to say "this test checks something" misled.

Approval in SeamSpec means the human saw the full test first (§12.4.3 rule 4). That stays. The question is how to help the human read it.

## Decision

`seamspec review` shows each item as **summary first, then the full test**, one item per screen. SeamSpec adds nothing that an agent wrote about its own test; everything in the summary comes from the record or is read out of the test file by SeamSpec itself (model-free, §3).

1. **Summary card.** Position (*"Proposed rule 1 of 3"*), title, the rule in its own words, where it applies, why it was proposed (the quoted origin), and the test's file and runner.
2. **"What this test checks".** SeamSpec lists the test's check lines above the code:
   - pytest: `assert` statements and `pytest.raises(...)` blocks, found with Python's `ast`, each with its line number;
   - vitest: lines containing `expect(`, found by a plain scan and labeled *"lines that look like checks"*, since that isn't a parse.
   It is a reading aid, not a verdict: it shows what is asserted, not whether that is enough.
3. **Quick facts and warnings.** Lines of test code and number of checks. Warnings when a test has **no checks**, is longer than 80 lines, or imports something a behavior test rarely needs (network or subprocess modules). Warnings never block.
4. **The full test, easier to read.** Line numbers; check lines highlighted and setup lines dimmed when the terminal supports color (`NO_COLOR` and non-terminals get plain text). Shown in full, above the approve prompt, as today.
5. **A clear red-green line.** *"Fails without your change: YES / NO / couldn't tell"*, on its own line next to the summary, once the editable-install bug is fixed (dogfooding finding #4).
6. **The agent says what its test doesn't cover.** The `lock` and `supersede` skills gain a step: before offering the review, tell the user in chat what the test does **not** check. This stays in the chat and is labeled as the agent's view; it is not stored and not shown by `seamspec review`.
7. **The same card in chat dialogs** (`open_review`, off by default): the summary and the check lines go first, so a client that shows only the top of a dialog shows the part that matters most. The full test still follows.

**Later, not now:**
- Old and new side by side for a replaced proposal or a supersede. It needs the earlier version to be kept (hands-on finding #7).
- The review page in the browser (ADR-20261006-c300 option B), which would carry all of the above with proper formatting. Decided after this change, if the terminal still feels cramped.

**Alternatives considered:**
- **Show an agent-written summary of the test in `seamspec review`.** Rejected: the agent would be describing its own work inside the screen that exists to check it. Its view belongs in the chat (item 6), where it is clearly the agent speaking.
- **Hide the test behind a "view" key.** Rejected: §12.4.3 rule 4. The test stays on screen before the approve prompt.
- **Ask a model to summarise the test.** Rejected: the core never calls a model (§3).

## Enforced Invariants

To be proposed when built: "review shows the full test before the approve prompt", and "the check list comes from the test file, never from the record's text".

## Consequences

* `seamspec review` output changes shape; the end-to-end review tests are updated with it.
* SPEC §11.4, §15 and §19.8b change in the implementing PR; §15.1 describes the plan until then.
* The skill templates and the generated plugin skills gain the "what it doesn't cover" step.
