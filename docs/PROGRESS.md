# Progress

The single place to see where the SeamSpec build stands. **Read this first** when picking up the work.

**Last updated:** 2026-10-05 · **Current:** v0.1 · Week 1 (due 2026-10-11): core ledger, `init` / `status` / `context`, schemas · [Week 1 issue](https://github.com/seamspec/seamspec/issues/1)

## Done

| Date | What | Where |
|---|---|---|
| 2026-10-05 | Design spec written, peer-reviewed, scope cut to Claude Code + pytest/vitest for v0.1 | `docs/SPEC.md`, §22, §26 |
| 2026-10-05 | Build process: build directly from SPEC, ADR for every spec change, dogfood from week 3 | ADR-20261005-ae6e |
| 2026-10-05 | v0.1 spec inconsistencies resolved (CI by mode, `CLAUDE.md` directive block, MCP wrapper, journal rules, approve fingerprints) | ADR-20261005-c41d |
| 2026-10-05 | Progress tracking: this file + `CLAUDE.md` as the agent entry point | ADR-20261005-2565 |
| 2026-10-05 | Names claimed (PyPI, npm, GitHub org); landing page live at seamspec.github.io; GitHub milestones + tracking issues #1–#7 created | GitHub |

## In progress

Nothing yet. No product code exists; Week 1 starts next.

## Next (Week 1, from issue #1)

- [ ] Package scaffold (uv, `pyproject.toml`, layout per SPEC §21, ruff, pytest) + GitHub Actions for the package's own tests
- [ ] `core/root.py`, `core/config.py` + `templates/config.toml`, `core/models.py`
- [ ] `core/store.py` (per-record files, atomic writes, file lock)
- [ ] `core/scope.py` (incl. `effective_protected_paths`) + `core/hashing.py`, `core/context.py`
- [ ] JSON Schemas v1: invariant, dead_end, config
- [ ] `seamspec init` scaffold, incl. `pytest.ini`, `vitest.config.mjs`, `.gitignore` entries and the marked `CLAUDE.md` directive block (§18; not yet on issue #1's checklist)
- [ ] `seamspec status`, `seamspec context <files>`

## Open questions (owner's call)

- Move the red-green check (SPEC §11.4) from week 2 to week 4? Week 2 is the heaviest week.
- Before the repo goes public: remove references to the unpublished `Idea.md` from SPEC.md.

## How to pick up this work

1. Read this file, then [`CLAUDE.md`](../CLAUDE.md) (working rules), then the current week's GitHub issue and SPEC §22.
2. Once code exists: `uv sync && uv run pytest` must pass before you start.
3. When you stop, update this file and tick the matching boxes in the week's GitHub issue, **in the same commit as the code** (ADR-20261005-2565).
