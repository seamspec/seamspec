---
id: ADR-20261018-6e1a
title: "Calibration fixes: capture what the user states, record each catch, count cost per prompt"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-18
scopes: ["seamspec/templates/directive.md", "seamspec/templates/commands/lock.md", "seamspec/templates/commands/dead-end.md", "seamspec/core/catches.py", "seamspec/adapters/claude.py", "seamspec/cli.py", "bench/harness/agent.py", "bench/harness/score.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261018-6e1a: Calibration fixes

## Context

The calibration runs for the capture and long-session benchmarks (ADR-20261015-c8e1) found three problems before any counted run.

1. **SeamSpec didn't capture what the user said.** With an empty ledger, the agent was told three agreements and a failed approach in session 1. It understood them, but proposed no rule and logged no dead end, then broke one agreement and reused the dead end in session 2. The protocol asked for a rule only "when you establish a new behavior worth protecting", and a dead end only "when an approach fails". The agent read both as its own work, not as what the user states. That is the capture flow SeamSpec promises ("rules you never wrote"), and the instructions didn't ask for it.
2. **Gate catches were invisible.** Claude Code's stream logs record the SessionStart hook but not Stop hooks, so the benchmark couldn't count how often SeamSpec sent the agent back. Users can't see it either: nothing records what SeamSpec caught.
3. **Cost was overstated.** Claude Code reports a session's running total after each prompt, and the harness added those totals up. The two calibration runs were reported as $1.06 and $7.17; they cost about $0.42 and $0.82. The earlier `full-1` batch was reported as $111.94 and really cost $45.37. Its C/A ratio moves from 1.17× to 1.16×, so that verdict stands.

## Decision

1. **Protocol: capture what the user states.**
   - **Rule 2:** *"When the user states an agreement or a rule the code must keep, or you establish a behavior worth protecting, capture it right away … If its code doesn't exist yet, say so and propose it once the code works."*
   - **Rule 3:** *"When an approach fails, or the user tells you about one that failed before, call `log_dead_end` …"*
   - **Rule 9** maps "an agreement the user states" to lock and "a failure the user describes" to dead-end.
   - The `lock` and `dead-end` commands' descriptions say the same, so hosts that pick a command by its description find them.
2. **A record of catches:** `.seamspec/.local/catches.jsonl`, one line per catch:
   - when the end-of-task check blocks finishing (`stop`, not counting hook errors);
   - when the commit check refuses a commit (`commit`).

   `seamspec status` shows *"caught N at the end of a task, M at a commit (this machine)"*. The benchmark counts gate catches from this record.
3. **The harness counts each prompt's own cost:** the increase in the session's running total.

**Alternatives considered:**
- **Leave the protocol alone and let capture fail in the counted run:** that would measure a wording gap, not the product's idea, and the fix is general (any user's stated agreements), not tuned to the tasks. N gets an equally explicit "write down what the user states" line, so the comparison stays fair.
- **Count catches from the agent's messages** (e.g. "SeamSpec blocked me"): it relies on the agent's wording.
- **Count catches from Claude Code's debug output:** fragile across versions, and users would still see nothing.

## Enforced Invariants

None yet.

## Consequences

- The capture calibration is rerun (about $0.50) before the counted runs. If the agent still proposes nothing, the counted capture run is not started, and the owner decides.
- The protocol block in `CLAUDE.md` and `AGENTS.md` changes; `init` updates it, and `directive_known_lines.txt` records the new lines.
- `full-1`'s write-up, SPEC §23 and PROGRESS now show the corrected cost.
- The benchmark estimate drops to about $40-45 for both batches.
