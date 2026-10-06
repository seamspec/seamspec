# Progress

The single place to see where the SeamSpec build stands. **Read this first** when picking up the work.

**Last updated:** 2026-10-05 · **Current:** v0.1 · Week 2 (due 2026-10-18): verifier, lifecycle, review, pre-commit · [Week 2 issue](https://github.com/seamspec/seamspec/issues/2)

## Done

| Date | What | Where |
|---|---|---|
| 2026-10-05 | **Week 2 · review** (PR `week-2/review`): `seamspec review` (runner config changes → new dead ends → supersede requests → proposals with full test + red-green), `core/redgreen.py` (HEAD in a temporary git worktree, `.venv`/`node_modules` linked). Fix: approving no longer silently confirms changed runner config. **Completes Week 2.** 216 tests | ADR-20261005-b7e2 |
| 2026-10-05 | Fixes from hands-on testing: files SeamSpec writes get normal permissions (were owner-only, finding #5); `init` ignores `.seamspec/**/__pycache__/` so bytecode no longer lands in the ledger (finding #6) | #13 |
| 2026-10-05 | Publishing gated: nothing goes to PyPI or npm without the owner's explicit go-ahead; no early pre-release | ADR-20261005-3adc |
| 2026-10-05 | **Week 2 · verify + gate** (PR `week-2/verify-gate`): `core/trust.py` (consent + trust incl. `harness` level), `core/tree.py`, `installers/git_hooks.py`; CLI `verify` (`--all`/`--changed`/`--proposed`/`--gate`/`--ci`/`--json`), `trust`, consent screen in `init` (`--accept-auto-run`). **Week 2 exit criteria pass end to end** with real `git commit` in Python and TypeScript repos. Fix: re-running `init` with consent now leaves advisory mode. 201 tests | ADR-20261005-8e80 |
| 2026-10-05 | **Week 2 · lifecycle** (PR `week-2/lifecycle`): `core/lifecycle.py` (propose / approve / reject / supersede / retire, `proposed/` → `harness_dir` → `retired/`, git-identity approver), `core/journal.py` (unjournaled-change check against git HEAD), `core/requests.py`, `core/adr.py`, `core/redact.py`; CLI `propose`, `dead-end`, `approve`, `reject`, `supersede` (`--request` for agents), `retire-dead-end`. Fix: the journal now flags `LOCKED → PROPOSED`. 177 tests | ADR-20261005-9c1a |
| 2026-10-05 | **Week 2 · verifier** (PR `week-2/verifier`): `core/verifier.py` + `core/reports.py`. Real pytest/vitest runs, per-rule attribution via JUnit + isolated reruns, empty/all-skipped = fail, process-group kill, one deadline with `incomplete`, scrubbed env with no verification flag, integrity + runner config fingerprints, `last_verify.json`. Fixes: `pythonpath = ..`, `--continue-on-collection-errors`, `init` records fingerprints; CI job `vitest`. 140 tests | ADR-20261005-4b1e |
| 2026-10-05 | **Week 1 code:** package scaffold (uv, flat layout, ruff, pytest, GitHub Actions on Python 3.11–3.14); `core/` root, config, models, store, scope, hashing, context, schemas, runners; JSON Schemas v1 (invariant, dead_end, config); `seamspec init` (ledger folders, `config.toml` from detected languages, `.seamspec/pytest.ini`, `.seamspec/vitest.config.mjs`, `.gitignore`, marked `CLAUDE.md` block), `seamspec status`, `seamspec context`. 112 tests, passing locally on 3.11, 3.12 and 3.14 | `seamspec/`, `tests/`, SPEC §19.1–§19.6a |
| 2026-10-05 | Branches + PRs for every change; PR template; owner squash-merges; `ci-ok` summary check for future rulesets (from Copilot's review of PR #8) | ADR-20261005-d8bc, PR #8 |
| 2026-10-05 | Week 1 implementation decisions (schema status rules require non-null values, unknown config keys are errors, store id validation, `render()` body only, §19 listings → contracts for implemented modules) | ADR-20261005-6f2a |
| 2026-10-05 | Progress tracking: this file + `CLAUDE.md` as the agent entry point | ADR-20261005-2565 |
| 2026-10-05 | v0.1 spec inconsistencies resolved (CI by mode, `CLAUDE.md` directive block, MCP wrapper, journal rules, approve fingerprints) | ADR-20261005-c41d |
| 2026-10-05 | Build process: build directly from SPEC, ADR for every spec change, dogfood from week 3 | ADR-20261005-ae6e |
| 2026-10-05 | Design spec written, peer-reviewed, scope cut to Claude Code + pytest/vitest for v0.1 | `docs/SPEC.md` §22, §26 |
| 2026-10-05 | Names claimed (PyPI, npm, GitHub org); landing page live at seamspec.github.io; GitHub milestones + tracking issues #1–#7 created | GitHub |

## In progress

- PR for `week-2/review` (completes Week 2): waiting for review and merge (fixes #5 and #6 merged in #13). After it merges: tick the review box on issue #2 and close the Week 2 milestone. The owner keeps hand-testing; Week 3 starts when the owner says go.

## Next (Week 2, issue #2)

- [x] `verifier` for pytest + vitest (§12.2, §19.7). Merged in #9
- [x] `lifecycle`: propose / approve / reject / supersede, journal, git identity (§11, §19.8). Merged in #10
- [x] `adr` module. Merged in #10
- [x] `review` with full test, red-green info and recent dead ends first (§11.4, §15). In review
- [x] `seamspec verify` CLI (`--all`, `--changed`, `--proposed`, `--gate`, `--ci`, `--json`). Merged in #11
- [x] Execution consent: `init` consent screen, `seamspec trust` (§12.4). Merged in #11
- [x] Pre-commit installer; `verify --gate` (§16.4). Merged in #11

## Open questions (owner's call)

- **Publishing to PyPI / npm:** waits for the owner's explicit go-ahead after thorough testing; no early pre-release (ADR-20261005-3adc). Try it meanwhile with `uv tool install --force --editable <path-to-repo>`.
- Before the repo goes public: remove references to the unpublished `Idea.md` from SPEC.md.

## How to pick up this work

1. Read this file, then [`CLAUDE.md`](../CLAUDE.md) (working rules), then the current week's GitHub issue and SPEC §22.
2. `uv sync && npm ci --prefix tests/fixtures/ts_repo && uv run pytest && uv run ruff check . && uv run ruff format --check .` must pass before you start (without the npm install, the vitest tests skip).
3. Try the CLI in a scratch repo: `uv run --project <this repo> seamspec init`, then `seamspec status` / `seamspec context <file>`.
4. Work on a branch and open a PR (ADR-20261005-d8bc). Update this file **in the same PR as the code**; tick the week's issue boxes once the PR is merged.
