---
id: ADR-20261026-5b8e
title: The commit check needs a redirect per runner that runs, none when nothing runs, and takes outside rule tests from disk
status: ACCEPTED
date: 2026-10-26
scopes: ["seamspec/core/snapshot.py", "seamspec/core/redgreen.py", "seamspec/cli.py", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# The commit check needs a redirect per runner that runs, none when nothing runs, and takes outside rule tests from disk

## Context

PRs #53 to #95 were merged while Copilot could only post a billing note. The catch-up review (draft #97, 2026-10-26) found three problems in the commit check's staged copy (ADR-20261014-3b1e). The check runs the rules against what the commit records when that differs from the files on disk:

1. **A new user's commits were blocked.** With an editable install (the default with `uv sync`), the check required proof that a redirect ran. With no approved rules, nothing runs, so there was never any proof, and every commit with an unstaged or untracked file was refused. That is exactly the state right after `seamspec init`. Reproduced; SeamSpec's own repository escaped it only because it has rules.
2. **One redirected runner vouched for another.** The proof was a single shared marker file. With two Python runners, say `pytest` (redirected) and `.venv/bin/pytest` (started by its path, so it can't be), the second could import the working tree's code and pass a broken staged change, while the first runner's marker made the run look trustworthy.
3. **vitest rule tests live in `tests/seamspec/`,** outside `.seamspec/`. A rule just approved but not staged was missing from the copy, so the commit was refused with "harness missing". `.seamspec/` was already taken from disk for exactly this case.

## Decision

1. **The redirect writes a marker of its own as well:** `applied.<script>` next to the shared `applied`, which red-green keeps using (`redgreen.applied_marker()`). `shim_runner()` returns the copy's file name instead of `True`.
2. **Proof per runner.** `Snapshot.evidence` maps each redirected runner to its marker. `Snapshot.no_python` holds runners known not to start Python: those whose start script's `#!` line names node, bun or deno (npx, vitest, jest), never python. Everything else that can't be redirected (a binary, `python -m`, `uv run`, a command given as a path) is treated as possibly Python. That fails closed, as before.
3. **Only the runners that matter.** `staged(root, cfg, runners)` gets the runners the selected rules use. With an editable install, it refuses before running anything if one of them is neither redirected nor Node. After the run, `trustworthy(ran)` checks the marker of each runner that actually ran. If nothing ran, nothing needs proof.
4. **Rule tests outside `.seamspec/` are part of the ledger** for the check: each runner's `harness_dir` outside `.seamspec/` is copied from disk, and `ledger_differs()` refuses a tracked file there whose staged copy differs from disk. The refusal now names every folder to `git add`.

**Alternatives considered:**
- *A separate `PATH` folder per runner:* the same proof, but the verifier would need a `PATH` per runner. A marker per start-script copy gives the same answer without that change.
- *Treat every runner that can't be redirected as non-Python unless it looks like Python:* fails open for `uv run pytest` or `python -m pytest`. Recognising Node and refusing the rest keeps the old safety.
- *Skip the staged copy when no rules apply:* it would fix finding 1 only. The per-runner check covers that case and finding 2 with one rule.

## Enforced Invariants

None new. Covered in `tests/test_commit_snapshot.py`:
- a commit with no rules in an editable project isn't blocked;
- every runner that ran needs its own marker;
- a runner that can't be redirected is refused before anything runs, but only when a rule uses it;
- Node runners need no redirect, binaries do;
- rule tests outside `.seamspec/` come from disk, and a changed tracked one is refused.

`tests/test_review.py` checks the new marker.

## Consequences

- Committing right after `init` works in an editable project with files not yet staged.
- A project whose Python runner is started by its path (`.venv/bin/pytest`) and is installed in editable mode gets the "stage your changes or stash" message for partial commits. That was already the case when it was the only runner; now it holds when another runner is redirected too.
- A vitest rule approved but not staged applies to the commit, the same as a pytest one.
