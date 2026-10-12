---
id: ADR-20261011-3c7e
title: Red-green points the HEAD run at HEAD's code when the project is installed in editable mode
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/core/redgreen.py", "seamspec/core/verifier.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-3c7e: Red-green points the HEAD run at HEAD's code when the project is installed in editable mode

## Context

Dogfooding finding #4 (2026-10-10). In the owner's project (a `src/` layout managed by `uv`), `seamspec review` answered *"fails without your change: no (it passes on HEAD too)"* for every rule, including rules for code that wasn't committed at all. Checked by hand against a clean copy of `HEAD`, the first rule's test failed there, so the right answer was "yes".

**Cause.** Red-green runs the test in a temporary `git worktree` of `HEAD` and links the project's `.venv` into it (§11.4). `uv sync` and `pip install -e` install the project in *editable* mode: the virtualenv doesn't hold the code, it holds a path to the **working tree** (a `.pth` line such as `/…/project/src`, or an import hook). So the HEAD run imported today's code and passed.

This is the worst kind of failure for this check. Red-green exists to catch a test that checks nothing, and here it reported exactly that, wrongly, for every good test. A reviewer would learn to ignore it.

**Constraint.** A locked rule in this repository (`inv_4b4f5ea7`, SPEC §12.4.7) says the only environment variable SeamSpec sets for a test run is `PATH`. Setting `PYTHONPATH` for the HEAD run would break it.

## Decision

1. **The HEAD run starts the runner through a copy of its start script.** When the runner's command is a plain name (`pytest`), SeamSpec finds the script it resolves to (with the same environment the verifier starts the runner with, so a runner's own `PATH` counts), writes a copy into a temporary folder with a few lines inserted at the top, and puts that folder first on `PATH` for the HEAD run only (`verifier.run(..., first_on_path=…)`). `PATH` stays the only variable SeamSpec sets.
2. **The inserted lines move import paths from the repository to the worktree** before anything else is imported:
   - every `sys.path` entry inside the repository (a `.pth` editable install, or a `PYTHONPATH` the user's environment carries) becomes the same path inside the worktree;
   - the tables of import-hook editable installs (`MAPPING` and `NAMESPACES` of `__editable__*` modules) are rewritten the same way;
   - the interpreter's own folders are left alone, since a virtualenv usually sits inside the repository.
   Paths are replaced, not shadowed, so a package that is entirely new since `HEAD` isn't found at all, which is correct.
3. **No guess when that isn't possible.** The copy can only be made for a text script with a Python `#!` line (including the three-line `/bin/sh` header installers write for long paths). It isn't made for a binary, a Windows launcher, a command given as a path, a script with a `from __future__` import anywhere in it, or a copy that wouldn't compile. The inserted lines leave a marker file when they run. If the project **has an editable install** (a `.pth` line pointing inside the repository, an `__editable__` hook naming it, or a `direct_url.json` marked editable) and the marker is missing after the run, the answer is **"n/a: this project is installed in editable mode, and the test couldn't be pointed at the last commit's code"**.
4. **A copy that didn't start is never trusted.** If a copy was made and its marker is missing after the run, the answer is "n/a: the test runner couldn't be started for the last commit's code", whether or not an editable install is present. A runner that failed to start would otherwise look like a failing test, which is a false "yes" (from Copilot's review of #47).
5. Projects without an editable install otherwise behave as before.

**Alternatives considered:**
- **Set `PYTHONPATH` for the HEAD run.** Simpler, but it breaks the locked "only PATH" rule, and it only shadows: a top-level package that is new since `HEAD` would still be found through the virtualenv's path.
- **Build a second virtualenv for the HEAD run.** Slow, needs the installer and often the network, and differs per packaging tool.
- **Answer "n/a" whenever an editable install is present.** Honest, but it would switch red-green off for most `uv` and `src/`-layout projects.
- **Don't link the virtualenv at all.** Then the test's dependencies are missing and nothing runs.

## Known limits

- Python processes that the test itself starts don't go through the copied script, so they aren't redirected.
- Windows start scripts are launchers, not text, so an editable install there gives "n/a".
- JavaScript workspaces whose `node_modules` links point back into the working tree have the same shape of problem. Tests that import through relative paths (SeamSpec's vitest hint) aren't affected; linked workspace packages are not handled yet.
- A virtualenv that carries its own `sitecustomize` is unaffected, because nothing is added to `sys.path`.

## Enforced Invariants

To be proposed: "red-green never answers 'no' for code that doesn't exist at HEAD because of an editable install".

## Consequences

* `verifier.build_env` and `verifier.run` gain `first_on_path`; only red-green passes it.
* SPEC §11.4, §19.7 and §19.8b are updated. Finding #4 in `docs/PROGRESS.md` is fixed.
* The owner's project can use the red-green line again (answer **Y** in review).
