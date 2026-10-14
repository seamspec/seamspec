---
id: ADR-20261014-3b1e
title: "The commit check tests what the commit records, not the files on disk"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-14
scopes: ["seamspec/core/snapshot.py", "seamspec/cli.py", "seamspec/core/redgreen.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261014-3b1e: The commit check tests what the commit records, not the files on disk

## Context

`git commit` records the index (what `git add` staged), not the working tree. The pre-commit gate (`seamspec verify --all --gate`, §16.4) ran the locked tests on the working tree. The owner found the gap while testing on Antigravity: a broken `cart.py` was staged with `git add -A`, then the agent fixed the file on disk only. A copy of that repository committed with "3 invariant(s) passed", and the commit recorded the broken file.

The same gap lets through code that needs a file that exists on disk but isn't staged, and a commit that stages a weakened rule test and then puts the approved one back on disk. "The agent may forget; the gate won't" has to hold for what is committed, so this is a correctness fix to the gate, not a convenience.

## Decision

When the index and the working tree differ (unstaged changes to tracked files, or untracked non-ignored files anywhere in the repository), the gate tests a copy of what the commit records:

1. **Copy the index** into a temporary folder with `git checkout-index --all`. The files on disk and the index are never touched, and the copy is always removed.
2. **Code from the index, ledger from disk.** The copy gets SeamSpec's ledger (`.seamspec/` without `.local/`) from disk: the ledger the CLI keeps and a human approved, the same one the Stop hook and `seamspec verify` run. A rule approved but not staged yet still applies.
3. **A staged ledger that differs from disk is refused** before anything runs ("SeamSpec's files staged for this commit differ from the ones on disk… Stage them again"), so a commit can't record rules the gate didn't run.
4. **Environments:** the copy links the project's `.venv` / `venv` / `node_modules`, and each runner whose start script is a Python script starts through red-green's start-script copy (§11.4), which points imports inside the repository at the copy. With an editable install, the run only counts if that redirect ran; otherwise the gate fails closed with a way out (stage the changes, or `git stash --keep-index --include-untracked`).
5. **Messages:** a pass says "N invariant(s) passed (on the staged files)." A refusal adds "Checked what this commit records (your staged files), which differs from the files on disk. If you fixed something after `git add`, stage it again." and leaves out the "Full test output: `seamspec verify --all`" hint, since that command runs the files on disk.

When the index matches the working tree, nothing changes: the gate runs in place as before and records the result for `seamspec status`. A run on the copy doesn't record it, since it isn't the state on disk. CI is unchanged: it checks out exactly what was pushed.

**Alternatives considered:**
- **`git stash --keep-index` around the run** (what many pre-commit tools do): it rewrites the person's files mid-commit, races an agent that is still editing, and can lose work if the run is interrupted or the stash doesn't apply back.
- **Refuse any commit with unstaged changes:** simple and safe, but it blocks the everyday "commit part of my work" flow.
- **Use the staged ledger instead of disk's:** a project that hasn't staged `.seamspec/` yet would commit code with no rules checked at all, while rules are approved on disk.

## Enforced Invariants

None yet. Candidate rule for SeamSpec's own ledger: "The commit check runs the locked tests against what the commit records" (`seamspec/core/snapshot.py`, `seamspec/cli.py`), with the test in `tests/test_commit_snapshot.py` as its basis.

## Consequences

- The gate is correct for partial commits: a commit passes or fails on what it records. Broken code left unstaged on disk doesn't block a good commit (the Stop hook still checks the disk).
- A commit with unstaged changes takes longer: about 8 seconds on SeamSpec's own repository (15 rules, editable install), mostly copying the index and starting the runner.
- `redgreen._shim_runner` becomes `redgreen.shim_runner`, shared by red-green and the gate.
- v0.1 runners are pytest and vitest, so linking `.venv` / `venv` / `node_modules` is enough. Runners added later (cargo, go) need their build caches considered here.
