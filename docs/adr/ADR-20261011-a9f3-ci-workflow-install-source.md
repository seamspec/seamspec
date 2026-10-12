---
id: ADR-20261011-a9f3
title: The CI workflow installs the SeamSpec version that wrote it; an unreleased build doesn't offer the workflow
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/installers/ci.py", "seamspec/templates/seamspec.yml", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-a9f3: The CI workflow installs the SeamSpec version that wrote it; an unreleased build doesn't offer the workflow

## Context

Dogfooding finding #1 (2026-10-08). `seamspec init` offered the CI workflow in the owner's new project, and the workflow it wrote ran `uv tool install seamspec`. SeamSpec isn't published: PyPI holds only a placeholder that reserves the name (publishing needs the owner's go-ahead, ADR-20261005-3adc). On a CI runner that step would install the placeholder, and `seamspec doctor --ci` would fail. The owner deleted the workflow.

Two further facts:

- The repository is private until the release, so a runner in another project can't install SeamSpec from it either. Giving the job a token would break §16.5: the verify job runs code from the pull request and gets no secrets.
- Even after the release, an unpinned `uv tool install seamspec` lets CI and the developer's machine run different SeamSpec versions, and the ledger checks (`doctor --ci`) can differ between versions.

## Decision

1. **A released SeamSpec pins itself.** The workflow gets `uv tool install "seamspec==<the version that wrote the file>"`, with a comment to update the line when SeamSpec is upgraded. "Released" means a version PyPI would carry: final, pre-release (`a`, `b`, `rc`) or post-release; a `.dev` or local (`+…`) version is not.
2. **An unreleased build doesn't offer the workflow.** In `enforced` mode, where `init` normally asks, it says instead: *"CI workflow: not offered yet. This SeamSpec isn't a released version, so the workflow would install it from its repository, which your CI may not be able to read. To add it anyway: `seamspec init --ci`."*
3. **Asked for explicitly, it is written honestly.** With `--ci`, or in `strict` mode (which always installs it), an unreleased build writes `uv tool install "git+https://github.com/seamspec/seamspec@main"`, with a comment in the file and a line in `init`'s output saying the CI must be able to read that repository and what to change after the release.
4. Everything else about the workflow stands (ADR-20261006-d16b): `pull_request` only, a read-only token, no secrets, the toolchain steps.

**Alternatives considered:**
- **Keep `uv tool install seamspec`.** It installs the placeholder today, and floats freely after the release.
- **Install from the repository with a token.** A secret in the job that runs pull-request code is what §16.5 forbids, and fork PRs get no secrets anyway.
- **Pin to a commit instead of `@main` for unreleased builds.** A local commit may not be pushed, so the pin could point at nothing. `main` is honest about being a moving target before the release.
- **Refuse `--ci` on an unreleased build.** The owner's own CI can be given read access to the repository; refusing would block that.

## Enforced Invariants

To be proposed: "the workflow never installs SeamSpec by an unpinned name".

## Consequences

* The owner's dogfooding project has no SeamSpec CI until the release, or until its CI can read the repository. Pre-commit and the Stop gate are unaffected.
* SPEC §7.3, §12A (installing), §16.5 and §19.6a are updated.
* Later: `doctor` could warn when the workflow pins a different SeamSpec version than the one running.
