---
id: ADR-20261013-4e9b
title: When a rule fails, say which rule and which check, before any test output
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/core/failtext.py", "seamspec/core/reports.py", "seamspec/core/verifier.py", "seamspec/cli.py", "seamspec/adapters/claude.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-4e9b: When a rule fails, say which rule and which check, before any test output

## Context

Dogfooding finding #11 (2026-10-12). The owner changed a locked behavior by hand and tried to commit. SeamSpec refused, correctly, with about 80 lines:

- `[FAIL] inv_246b5fb8 (pytest)`: the rule's id, never its title ("The gateway gives up after exactly 5 attempts by default").
- The same pytest failure three times, once per parametrized case.
- The one line that mattered, `assert 4 == 5`, in the middle.

This is the screen a new user sees the first time SeamSpec stops them. The readable review (ADR-20261011-8013) fixed the same problem for approvals; the moment of refusal had been left as raw runner output. SPEC §16.1 already showed the Stop hook's message with the rule's title in it; the code had never done that.

## Decision

1. **One short block per failing rule**, in every failure report:

   ```
     inv_246b5fb8 · The gateway gives up after exactly 5 attempts by default
       line 29: assert len(backend.requests) == 5
         AssertionError: assert 4 == 5  (3 test cases)
       Test: .seamspec/tests/test_inv_246b5fb8.py
   ```

   The title comes from the ledger. The line number and the message come from the runner's JUnit report (already required for knowing which rule failed, §12A.4). The text of the line is read from the rule's test file. Identical failures are counted, not repeated.
2. **At a refused commit** (`verify --gate`) the output is *"SeamSpec: commit blocked."*, the blocks, how to proceed, and *"Full test output: `seamspec verify --all`"*. The runner's own output is left out for every failure a block explains.
3. **A plain `seamspec verify` and CI** keep the runner's output and print the blocks after it, last, where the eye lands in a terminal and at the end of a CI log.
4. **The Stop hook** (the agent's view) puts the blocks first and the runner's output after them. The agent needs the detail to fix the code, and Claude Code keeps only the start of a long hook message.
5. **A summary never hides a failure.** When the report can't say what failed (a timeout, a runner that couldn't start, no usable report, a group nobody could attribute), the rule is still listed with that reason, and the runner's output for that group is shown in every mode, the refused commit included. A tampered test, or one that ran nothing, gets a block with that reason.
6. `RunnerResult` gains `checks` (per invariant: line, message, number of cases). It appears in `seamspec verify --json`, `last_verify.json` and the `verify` tool's result.

**Alternatives considered:**
- **Parse pytest's terminal output** for the "short test summary" lines. It breaks with plugins, colors, other runners and SeamSpec's own truncation of long output. The JUnit report is structured and both shipped runners write it.
- **Change the runner presets** (`--tb=short`, `-q -q`). That edits each project's `config.toml` and its fingerprints, still names no rule, and still repeats per case.
- **Summary first, full output after, at a refused commit too.** In a terminal the summary would scroll off the top; that is the problem being fixed.
- **Hide the runner's output everywhere.** CI logs can't be re-run locally in the same environment, and the agent fixes code from the traceback.

## Enforced Invariants

To be proposed: "a refused commit names each failing rule by id and title".

## Consequences

- The first refusal a user sees is a few lines that name the rule in their own words.
- Tools that read `verify --json` see one more field per result; nothing was removed.
- The text of a refused commit changed: scripts matching `[FAIL] <id> (<runner>)` in pre-commit output must match the new block (the Stop hook and a plain `verify` still print that line).
- Runners without a JUnit report (`report = "none"`) get the reason line and their raw output, as before.
