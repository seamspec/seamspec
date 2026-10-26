---
id: ADR-20261026-f4e2
title: Full CI on every pull request, macOS included, now the repo is public
status: ACCEPTED
date: 2026-10-26
scopes: [".github/workflows/tests.yml", "CLAUDE.md", "docs/SPEC.md"]
invariants: []
supersedes: ADR-20261007-d757
superseded_by: null
---

# Full CI on every pull request, macOS included, now the repo is public

## Context

ADR-20261007-d757 trimmed pull-request CI to fit a private repository's monthly Actions minutes, in which macOS counted 10×:
- pull requests ran Python 3.11 and 3.14 only;
- Python 3.12, 3.13 and macOS ran only after a merge to `main`, so a problem there showed up on `main`, not on the PR.

On 2026-10-26 the repository went public (ADR-20261026-1c7a). Standard GitHub-hosted runners, macOS included, are free for public repositories, so the reason for the trim is gone. The owner develops on macOS, and macOS has differed from Linux before (path handling, `/bin/sh`, process groups).

## Decision

1. **Pull requests run the same jobs as `main`:**
   - Python 3.11, 3.12, 3.13 and 3.14 on Linux;
   - Python 3.12 on macOS (`test-macos`);
   - vitest;
   - the SeamSpec check.
2. **`ci-ok` also needs `test-macos`,** so a PR that fails only on macOS can't be merged once `ci-ok` is a required check (release step 4).
3. **Concurrency stays:** a new push to a PR cancels the run for its previous commit. That isn't about cost: an outdated run is useless.
4. **Copilot reviews are requested automatically** by the `main` ruleset, now enforced on the public repo. Requesting one by hand (ADR-20261005-c076 step 1) becomes the fallback, as point 5 of that ADR expected. `CLAUDE.md` says so.

**Alternatives considered:**
- *Keep macOS after merge only:* the reason was cost, and that's gone. Finding a macOS problem after merge means a follow-up PR on a broken `main`.
- *macOS on every Python version:* four slower jobs for little gain. Version differences show up on Linux, and platform differences show up on any single version.

## Enforced Invariants

None.

## Consequences

- PR checks take a few minutes longer, since macOS runners are slower to start. The cost stays zero while the repo is public.
- If the repository ever went private again, this would need revisiting, together with billing.
- SPEC §21 describes the new jobs.
