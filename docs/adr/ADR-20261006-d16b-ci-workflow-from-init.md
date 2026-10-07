---
id: ADR-20261006-d16b
title: The CI workflow and CODEOWNERS that init installs
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-06
scopes: ["seamspec/installers/ci.py", "seamspec/templates/seamspec.yml", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261006-d16b: The CI workflow and CODEOWNERS that init installs

## Context
SPEC §7.3 and §16.5 define CI by mode: never in advisory, offered in enforced, always in strict (plus CODEOWNERS). The workflow runs `doctor --ci` and `verify --all --ci`. `doctor --ci` landed in #30. The SPEC's workflow left the toolchain steps as comments for the user to fill in, so a fresh project's CI would fail until someone edited it.

## Decision
1. **`init` writes `.github/workflows/seamspec.yml`** from `seamspec/templates/seamspec.yml`, and **never overwrites** an existing one (`kept`).
   - The trigger is `pull_request`, never `pull_request_target`.
   - The job has read-only `contents` and `fetch-depth: 0`, and runs `doctor --ci` before `verify --all --ci`.
2. **Toolchain steps are chosen from what `init` finds,** so the workflow works without edits in the common cases:
   - **pytest:**
     - `uv sync --locked` when `uv.lock` exists;
     - else `uv venv && uv pip install -r requirements.txt pytest`;
     - else `uv venv && uv pip install pytest` (a comment says to add the project's dependencies).

     SeamSpec's verifier finds `pytest` in `.venv` (ADR-20261005-9b8f).
   - **vitest:** `actions/setup-node@v4`, then `npm ci` when `package-lock.json` exists, else `npm install`.
   - **Nothing detected:** a comment where the steps go.
3. **The flag and the question:** `init --ci/--no-ci`.
   - **Enforced** asks *"Add a CI workflow … that runs your approved rules on every PR? [Y/n]"*. Without a terminal and without a flag it adds nothing, and prints `seamspec init --ci`, like the plugin step (ADR-20261005-428a).
   - **Strict** always adds it, and says so when `--no-ci` is given.
   - **Advisory** never does, and says so when `--ci` is given.
4. **CODEOWNERS (strict).** A marked block between `# seamspec:begin` and `# seamspec:end` in `.github/CODEOWNERS` owns `/.seamspec/` and each runner's harness folder, with the placeholder owner `@your-team/leads`, which the human replaces. Only the block is SeamSpec's: other lines are kept, and rerunning updates the block in place.
5. **Before the release,** `uv tool install seamspec` installs only the 0.0.x placeholder. The workflow is written for the release, which stays gated (ADR-20261005-3adc). This repo's own CI runs SeamSpec from the checkout (`uv run seamspec …`).

**Alternatives considered:**
- *Leave the toolchain as comments (§16.5 as first written):* rejected. A fresh project's first PR would fail CI for setup reasons, not rule reasons.
- *Merge into an existing `seamspec.yml`:* rejected. Workflows get hand-edited; overwriting or merging YAML risks breaking a user's CI. `doctor` could warn about drift later.
- *A real team in CODEOWNERS:* `init` can't know it; the placeholder is explicit and the message says to replace it.

## Enforced Invariants
None yet. Dogfooding candidate: "the generated workflow never uses pull_request_target and keeps contents: read".

## Consequences
* Week 4's CI deliverable is complete in code. The exit criterion, "CI blocks a regression and lists retirements on a test PR", is shown next on this repo with a throwaway test PR.
* SPEC §16.5 (workflow snippet), §19.6a and §21 are updated in the same PR.
