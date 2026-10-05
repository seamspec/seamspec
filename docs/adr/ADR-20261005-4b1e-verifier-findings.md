---
id: ADR-20261005-4b1e
title: Verifier fixes found by running real pytest and vitest
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/core/verifier.py", "seamspec/core/reports.py", "seamspec/templates/**", "seamspec/installers/scaffold.py", ".github/workflows/tests.yml"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-4b1e: Verifier fixes found by running real pytest and vitest

## Context
Week 2's first slice implemented `core/verifier.py` and `core/reports.py` (SPEC §12.2, §12A.4, §19.7) and tested them against real pytest and vitest runs in throwaway repos, instead of against mocked output. That exposed four problems in the week 1 templates and the spec.

## Decision

1. **`.seamspec/pytest.ini` uses `pythonpath = ..`, not `.`** pytest resolves `pythonpath` relative to the ini file's folder (`.seamspec/`), not to `--rootdir`. With `.`, no harness could import project code. This is a week 1 template bug; there are no installs to migrate.
2. **The pytest preset adds `--continue-on-collection-errors`.** Without it, one harness that fails to import stops pytest before the others run. Those then appear empty in the report and would be blamed as failing.
3. **`init` records runner config fingerprints** for the files it writes, when `.seamspec/fingerprints.json` doesn't exist yet. Running `init` is a human action, and without this the first `verify` (and pre-commit) after `init` would fail with "runner config changed". Later changes still need confirming in `seamspec review`. A missing runner config file is now a failure too.
4. **A harness absent from a usable report counts as empty, and so as failing** (with decision 2, "absent" really means nothing was collected). Isolated reruns remain the fallback when no report is usable.
5. **Tests run the real tools.** `tests/fixtures/ts_repo` pins vitest 3.2.7 (installed with `npm ci --prefix tests/fixtures/ts_repo`). A new CI job `vitest` installs it and runs the vitest tests with `SEAMSPEC_REQUIRE_VITEST=1`, so a missing install fails instead of skipping. `ci-ok` now requires both `test` and `vitest`.

**Verified, no change needed:** SeamSpec's own `vitest.config.mjs` keeps a project's `vitest.config.ts` `setupFiles` out, and vitest's JUnit `classname` carries the harness path, so attribution works. `-c .seamspec/pytest.ini` already keeps a *root* `conftest.py` out (pytest only collects conftests below the ini folder); `--noconftest` is what stops a conftest planted next to the harnesses.

**Alternatives considered:**
- *Mock runner output in tests:* rejected; mocks would have hidden decisions 1 and 2.
- *Leave first-run fingerprints to `review`:* rejected; every fresh repo would start with a failing gate.

## Enforced Invariants
None yet. Candidates when SeamSpec governs its own repo (week 3): "a harness that skips every test fails verification", "a conftest planted next to harnesses has no effect", "a timed-out runner leaves no child processes".

## Consequences
* SPEC §9.5, §12.2, §12.3, §12A.6, §19.7 (now a contract) and §21 are updated in the same PR.
* CI gains a Node setup and a ~24 MB npm install in the `vitest` job.
* Locally, the vitest tests skip until `npm ci --prefix tests/fixtures/ts_repo` has been run.
