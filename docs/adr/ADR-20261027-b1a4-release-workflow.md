---
id: ADR-20261027-b1a4
title: A pushed version tag publishes to PyPI through trusted publishing, after checks
status: ACCEPTED
date: 2026-10-27
scopes: [".github/workflows/release.yml", "CHANGELOG.md", "CONTRIBUTING.md", "tests/test_packaging.py", "docs/SPEC.md", "docs/PROGRESS.md"]
invariants: []
supersedes: null
superseded_by: null
---

# A pushed version tag publishes to PyPI through trusted publishing, after checks

## Context

Release step 6 publishes 0.1.0 (the owner: "start step 6", 2026-10-27). The repository had no way to upload a package. Uploading from a laptop needs a PyPI token stored somewhere, and the package would be built with whatever uv that machine has. That is the problem ADR-20261026-d67b pinned uv in CI to avoid.

PyPI's *trusted publishing* lets a named GitHub workflow upload without any stored secret. PyPI checks a short-lived token GitHub issues for that workflow run.

## Decision

1. **`.github/workflows/release.yml` runs when a `v*` tag is pushed,** and only then. Pushing the tag is the release decision, and it stays the owner's (ADR-20261005-3adc).
2. **Before building, it refuses a tag that:**
   - doesn't match `seamspec.__version__`;
   - points to a commit that isn't on `main`;
   - or has no dated `CHANGELOG.md` entry (`## [<version>] - YYYY-MM-DD`).

   It then runs the test suite and builds the wheel and sdist once, with the uv pinned in the tests (0.9.28).
3. **A separate `publish` job uploads** with `uv publish --trusted-publishing always`. It runs in the GitHub environment `pypi`, and it is the only job with `id-token: write`. The build job can't publish, and the publish job runs no project code.
4. **The owner sets up the PyPI side:** a trusted publisher for `seamspec/seamspec`, workflow `release.yml`, environment `pypi`. The owner can also add a required reviewer to the `pypi` environment on GitHub. The upload then waits for a click, even after the tag is pushed.
5. **Tests** (`tests/test_packaging.py`):
   - a released version must have a dated changelog entry, so the PR that sets the version fails before anyone tags it;
   - `release.yml` must use the same uv as `tests.yml`.
6. **The changelog's 0.1.0 entry is dated 2026-10-27.** If the tag is pushed on a later day, a one-line PR moves the date first.
7. **The GitHub Release is made by hand** (`gh release create`) after PyPI has the package, from the changelog entry. The workflow then needs no write access to the repository.

**Alternatives considered:**
- *`pypa/gh-action-pypi-publish`:* PyPA's own action, and it adds signed attestations. It is one more outside dependency in the release path, though, and it uploads with a different tool than the one that built the package. `uv publish` uploads what the pinned uv built. Attestations can be added later.
- *Run the release on a GitHub Release event:* then a draft Release must exist before the package does. The tag is the simpler trigger.
- *Upload from the maintainer's machine with a token:* that means a stored secret, and the package isn't built by the pinned uv.

## Enforced Invariants

None new. `tests/test_packaging.py::test_one_version_everywhere` (the dated entry) and `::test_the_release_is_built_with_the_uv_the_tests_use`.

## Consequences

- A release is one `git push origin v<version>` once the version PR is merged and PyPI trusts the workflow. A mistaken tag fails before anything is uploaded.
- PyPI never accepts the same version twice. If an upload goes wrong after it starts, the fix is a new version, not a retry with different files.
- Upgrading uv (planned after 0.1.0) moves the pin in both workflows; the test fails if only one moves.
