---
id: ADR-20261026-d67b
title: Pin uv in SeamSpec's own CI; upgrade it on purpose
status: ACCEPTED
date: 2026-10-26
scopes: [".github/workflows/tests.yml"]
invariants: []
supersedes: null
superseded_by: null
---

# Pin uv in SeamSpec's own CI; upgrade it on purpose

## Context

The first CI run on the public repository (#96) failed one test, `test_the_sdist_has_nothing_from_outside_the_package` (ADR-20261024-b3e9). The source package had an extra top-level file, `pyproject.toml.orig`. The same test passed locally, and a package built from a fresh clone had no such file.

The difference was uv. `astral-sh/setup-uv` installs the newest uv unless told otherwise: CI got 0.13.5, while the maintainer's machine has 0.9.28. With CI pinned to 0.9.28 the run passed, with nothing else changed. So the newer uv builds a different package from the same code. uv 0.13.0 also lists changes to how source packages are built ("different archive bytes and hashes"). We haven't traced exactly which change adds the file.

The file would have been harmless: a copy of `pyproject.toml`, nothing private. The problem is that CI was testing with a tool nobody had chosen, and it changed without anyone noticing. The release package (release step 6) will be built in CI, so it would have been built with that tool too.

## Decision

1. **Every `setup-uv` step in `.github/workflows/tests.yml` pins `version: "0.9.28"`**, the version the release was rehearsed with (ADR-20261024-b3e9).
2. **The publish workflow (release step 6) uses the same pin**, so the package uploaded to PyPI is built by the uv the tests ran with.
3. **Upgrading uv is a deliberate change, in a PR of its own:** move the pin, then:
   - update the `uv_build` bound in `[build-system]` if the new version needs it;
   - run the full suite, including `tests/test_packaging.py`;
   - look at what the built wheel and source package contain;
   - if the contents change, say why in the PR and update the packaging test.

   It is planned for after v0.1.0, not before.
4. The workflow SeamSpec installs into user repositories (`seamspec/templates/seamspec.yml`) is unchanged. It installs SeamSpec and runs its checks; it doesn't build packages.

**Alternatives considered:**
- *Allow `pyproject.toml.orig` in the packaging test.* That fixes today's failure but keeps CI on whatever uv is newest, so the next change would surprise us the same way.
- *Upgrade to 0.13.5 now.* It's a breaking release for packaging, just before the first release, with nothing we need from it. Better done calmly after v0.1.0.
- *`required-version` in `[tool.uv]`.* One pin for CI and every contributor's machine, but it refuses anyone with a different uv. Too strict for contributors.

## Enforced Invariants

None. `tests/test_packaging.py` already fails when the package contents change.

## Consequences

- CI and the release build use the same uv as the maintainer's machine.
- A newer uv no longer reaches CI by itself. The pin has to be moved by hand, and that is now on the list after v0.1.0 (PROGRESS).
