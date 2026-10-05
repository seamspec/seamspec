---
id: ADR-20261005-3adc
title: Publishing to PyPI or npm needs the owner's explicit go-ahead
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["pyproject.toml", "docs/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-3adc: Publishing to PyPI or npm needs the owner's explicit go-ahead

## Context
The names `seamspec` on PyPI (0.0.3) and npm (0.0.1) hold placeholders that only print a message. The roadmap (SPEC §22) put the real PyPI release at the week 6 launch, and an early pre-release (e.g. `0.1.0a1` after week 3) was floated as an option. The owner wants to test the tool thoroughly across several weeks of implementation before anything real is published.

## Decision

1. **Nothing is published to PyPI or npm without the owner's explicit confirmation**, given in the conversation for that specific release. That covers real releases, pre-releases (`a`, `b`, `rc`), placeholder bumps and the v0.2 `npx` wrapper.
2. **No early pre-release** (e.g. `0.1.0a1` after week 3) unless the owner asks for one.
3. **Building continues week by week as planned.** Only publishing is gated. Week 6's "PyPI release" exit criterion becomes "release ready to publish; published once the owner confirms".
4. Until then, the way to try SeamSpec is an editable install from a local checkout: `uv tool install --force --editable <path-to-repo>`.

**Alternatives considered:**
- *Publish at week 6 automatically:* rejected; the owner decides when it has been tested enough.
- *Early pre-release after week 3:* rejected for now; the owner may request it later.

## Enforced Invariants
None (release process decision).

## Consequences
* Agents working on this repo must never run `uv publish`, `twine upload`, `npm publish` or similar on their own. `CLAUDE.md` states this rule.
* The launch date in SPEC §22 is a target for being *ready*, not for publishing.
