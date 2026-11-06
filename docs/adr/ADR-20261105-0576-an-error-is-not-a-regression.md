---
id: ADR-20261105-0576
title: A test that stops with an error isn't reported as a regression
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/core/reports.py", "seamspec/core/failtext.py", "seamspec/cli.py", "seamspec/adapters/claude.py"]
invariants: []
supersedes: null
superseded_by: null
---

# A test that stops with an error isn't reported as a regression

## Context

While dogfooding on SessionWalk, a rule's test that couldn't even start got the same advice as one whose check failed: *"Fix the regression, or if the change is intentional, supersede the rule"*, and, for the agent, *"call request_supersede"*. For a setup problem (a missing package, the wrong Python, a broken conftest) that is the wrong fix, and the supersede half points the agent at retiring a rule that isn't broken.

pytest already tells the two apart in its JUnit report: a check that failed is a `<failure>`; a test that stopped while importing, setting up or tearing down is an `<error>`. SeamSpec read both as "failed".

## Decision

- **`FailedCheck` records `errored`** for pytest's `<error>`. Its summary line ends with *"(an error, not a failed check)"*.
- **`failtext.did_not_start(report)`** is true when rules failed but no check did: every failing test errored or couldn't be started (`could_not_run`). A timeout, an edited test, a runner config change, a journal problem, a failure the report doesn't explain, or any failed check makes it false, so the regression wording stays whenever a regression is possible.
- **Then the advice changes.** `seamspec verify` (and the commit check) ends with *"No check failed: … Fix that, then run `seamspec verify` again."*. The Stop hook tells the agent to fix the error, to treat it as a regression only if it comes from its own change to code the test imports, and not to call `request_supersede` for a setup problem.
- **The error advice comes first.** For a rule whose retirement a person declined, the decline is still shown, but an error gets the error advice, not *"Fix the regression: a person already decided to keep these rules"*: the rule can break for reasons that have nothing to do with the declined change. A timeout anywhere in the run keeps the regression wording, even when the Stop deadline also marked that group incomplete (both found by Copilot on #113).
- **The block still blocks.** The commit and the agent's stop are refused as before: a rule that can't run isn't a rule that holds.

Alternatives: treating every import error as setup, rejected because renaming a function a rule imports is a real regression, so the text names both causes; counting these blocks separately in `catches.jsonl`, left for later because the benchmark reads that file as is.

## Enforced Invariants

None new.

## Consequences

- People and agents get advice that matches what happened. An agent is less likely to ask to retire a rule because of its environment.
- vitest's JUnit report marks thrown errors as failures, so vitest keeps the regression wording. A runner that can't start at all gets the new wording on every runner.
