---
id: ADR-20261005-b7e2
title: seamspec review, red-green check, and explicit runner-config confirmation
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/review.py", "seamspec/core/redgreen.py", "seamspec/core/lifecycle.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-b7e2: seamspec review, red-green check, and explicit runner-config confirmation

## Context
The last Week 2 slice is `seamspec review` with the red-green check (SPEC §11.3, §11.4, §15). Building it exposed a gap from the lifecycle slice, and left a few details for this ADR to decide.

## Decision

1. **Approving a rule no longer silently confirms changed runner config.** Before, `approve` wrote the current runner config fingerprints on success, so an edited `.seamspec/pytest.ini` was accepted along with any approval, without anyone seeing it. `lifecycle.approve` now refuses on a fingerprint mismatch unless called with `confirm_config=True`. `seamspec review` asks about config changes first (until they're confirmed, approvals are blocked); `seamspec approve` shows the changed files and asks.
2. **The red-green check runs only after the reviewer has seen the test and said yes** ("Run it now to check it fails without your change? [Y/n]", default yes). The test is agent-written code, and §12.4.3 rule 4 asks that the human sees it before it runs.
3. **Red-green mechanics:** run on the working tree first (`n/a` if it fails there), then in a detached `git worktree` of `HEAD`. The worktree gets SeamSpec's *current* `config.toml` and runner config files (so both runs use the same runner, even if `.seamspec/` isn't committed yet) and links to `.venv` / `venv` / `node_modules`. It works when `.seamspec/` is in a subfolder, and the worktree is always removed.
4. **Review order:** runner config changes, then dead ends recorded since the last review (`.local/review.json`), then supersede requests (approve / decline / skip; declining deletes the request), then proposals oldest first. `q` stops at any point; undecided items stay waiting.
5. **Prompt-driven, not full-screen.** One-letter answers, re-asked on invalid input. This works in any terminal and in end-to-end tests; a full-screen TUI can come later if reviews get long.
6. **Lists are ordered by creation time, ties broken by id.** Random ids alone made the order unpredictable, which made one test flaky. The same unpredictability would have confused reviewers.

**Alternatives considered:**
- *Keep silent config confirmation on approve:* rejected; it let a changed runner config through without anyone seeing it.
- *Run red-green automatically before showing the test:* rejected; agent-written code would run before the human had seen it.
- *Use `click.Choice` for the key prompts:* not possible; the installed typer no longer depends on click.

## Enforced Invariants
None yet. Week 3 candidates: "approving never confirms changed runner config without an explicit yes", "red-green leaves no worktree behind".

## Consequences
* Week 2's deliverables are complete once this merges.
* SPEC §11.4, §12.2, §15 (review and approve rows), §19.8b and §21 are updated in the same PR.
* Hand-testing gains a step: `seamspec review` replaces one-by-one `approve` / `reject` in the checklist.
