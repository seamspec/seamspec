# Progress

The single place to see where the SeamSpec build stands. **Read this first** when picking up the work.

**Last updated:** 2026-10-05 · **Current:** v0.1 · Week 1 (due 2026-10-11): core ledger, `init` / `status` / `context`, schemas · [Week 1 issue](https://github.com/seamspec/seamspec/issues/1)

## Done

| Date | What | Where |
|---|---|---|
| 2026-10-05 | **Week 1 code:** package scaffold (uv, flat layout, ruff, pytest, GitHub Actions on Python 3.11–3.14); `core/` root, config, models, store, scope, hashing, context, schemas, runners; JSON Schemas v1 (invariant, dead_end, config); `seamspec init` (ledger folders, `config.toml` from detected languages, `.seamspec/pytest.ini`, `.seamspec/vitest.config.mjs`, `.gitignore`, marked `CLAUDE.md` block), `seamspec status`, `seamspec context`. 112 tests, passing locally on 3.11, 3.12 and 3.14 | `seamspec/`, `tests/`, SPEC §19.1–§19.6a |
| 2026-10-05 | Branches + PRs for every change; PR template; owner squash-merges; `ci-ok` summary check for future rulesets (from Copilot's review of PR #8) | ADR-20261005-d8bc, PR #8 |
| 2026-10-05 | Week 1 implementation decisions (schema status rules require non-null values, unknown config keys are errors, store id validation, `render()` body only, §19 listings → contracts for implemented modules) | ADR-20261005-6f2a |
| 2026-10-05 | Progress tracking: this file + `CLAUDE.md` as the agent entry point | ADR-20261005-2565 |
| 2026-10-05 | v0.1 spec inconsistencies resolved (CI by mode, `CLAUDE.md` directive block, MCP wrapper, journal rules, approve fingerprints) | ADR-20261005-c41d |
| 2026-10-05 | Build process: build directly from SPEC, ADR for every spec change, dogfood from week 3 | ADR-20261005-ae6e |
| 2026-10-05 | Design spec written, peer-reviewed, scope cut to Claude Code + pytest/vitest for v0.1 | `docs/SPEC.md` §22, §26 |
| 2026-10-05 | Names claimed (PyPI, npm, GitHub org); landing page live at seamspec.github.io; GitHub milestones + tracking issues #1–#7 created | GitHub |

## In progress

- Nothing. **Week 1 is complete:** CI passed on all 5 jobs (Python 3.11–3.14 on Linux, 3.12 on macOS) on PR #8, which contains all of the Week 1 code. The first runs on `main` (run 37368198257) never started because of a GitHub Actions incident. Once PR #8 merges: tick issue #1 and close the Week 1 milestone.

## Next (Week 2, issue #2)

- [ ] `verifier` for pytest + vitest: `{each}` / `{report}` expansion, process-group kill, one overall deadline, integrity + runner config fingerprints, empty/skipped = fail, env scrubbing, JUnit attribution + isolated reruns (§12.2, §19.7)
- [ ] `lifecycle`: propose / approve / reject / supersede, `proposed/` → `harness_dir`, journal, git identity (§11, §19.8)
- [ ] `adr` module; `review` TUI with harness, red-green info and recent dead ends first (§11.4, §15)
- [ ] Execution consent: `init` consent screen, `seamspec trust` (§12.4)
- [ ] Pre-commit installer; `verify --gate` (§16.4)

## Open questions (owner's call)

- Move the red-green check (SPEC §11.4) from week 2 to week 4? Week 2 is the heaviest week.
- `.seamspec/vitest.config.mjs` hasn't been run against a real vitest install yet; check it in week 2 with the TypeScript fixture.
- Before the repo goes public: remove references to the unpublished `Idea.md` from SPEC.md.

## How to pick up this work

1. Read this file, then [`CLAUDE.md`](../CLAUDE.md) (working rules), then the current week's GitHub issue and SPEC §22.
2. `uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .` must pass before you start.
3. Try the CLI in a scratch repo: `uv run --project <this repo> seamspec init`, then `seamspec status` / `seamspec context <file>`.
4. Work on a branch and open a PR (ADR-20261005-d8bc). Update this file **in the same PR as the code**; tick the week's issue boxes once the PR is merged.
