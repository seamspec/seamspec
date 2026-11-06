---
id: ADR-20261105-e2c9
title: The reviewer's "My read" follows the gaps it listed
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/templates/agents/reviewer.md", "seamspec-plugin/agents/reviewer.md"]
invariants: []
supersedes: null
superseded_by: null
---

# The reviewer's "My read" follows the gaps it listed

## Context

On SessionWalk, the owner ran `/seamspec-explain` on the same two proposed rules in Claude Code and in Antigravity. Both reviewers found the same real gaps under "What it doesn't check": a promise about sessions with several prompts tested only with one prompt, a `VAR=1` wrapper clause promised in the rule but never tested, and code that let a failing subagent check count as backing a claim. Claude's reviewer then said "ask for changes first"; Antigravity's argued the gaps away and said "looks sound to approve".

The template asked for one of three verdicts "with one sentence of reasoning", with nothing tying the verdict to the gaps above it. A more agreeable model filled that space with reassurance. "My read" is the line a hurried reviewer reads, so an approval there after listed gaps undoes the point of the reviewer (§15.3).

## Decision

"My read" is chosen by a rule, written into the reviewer's prompt (all hosts render it from the same template):

- **"ask for changes first"**, naming the specific change, whenever "What it doesn't check" or "Look closely at" found a part of what the rule promises that the test never exercises, a test that would still pass if a core part of the promise broke, or a mismatch between what the rule says and what the code does. A gap listed above may not be argued away in "My read".
- **"looks sound to approve"** only when every part of the promise is tested directly and the code does what the rule says.
- **"can't tell"** when the reviewer couldn't read enough to decide.

Gaps outside the promise (say, performance a rule never mentions) don't force "ask for changes first".

Alternatives: dropping "My read" altogether, rejected because the owner finds it useful and SeamSpec's facts and red-green still sit beside it in `seamspec review`; having SeamSpec parse the answer and flag a contradiction, rejected because the core stays model-free and doesn't grade the reviewer's prose (§3).

## Enforced Invariants

None new. A test checks that every host's copy of the reviewer carries the rule.

## Consequences

- More "ask for changes first" from agreeable models, which is the safer error: the person can still approve in `seamspec review`.
- A prompt can't guarantee a model obeys it. This narrows the gap; it doesn't close it, and the decision stays with the person.
- Existing installs get the new wording when `seamspec init` (or `--hosts`) is rerun; the Claude Code plugin gets it with the next release.
