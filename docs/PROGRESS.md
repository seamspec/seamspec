# Progress

The single place to see where the SeamSpec build stands. **Read this first** when picking up the work.

**Last updated:** 2026-10-06 · **Current:** v0.1 · Week 4: CI, doctor, remaining skills, dogfooding · [Week 4 issue](https://github.com/seamspec/seamspec/issues/4)

## Done

| Date | What | Where |
|---|---|---|
| 2026-10-06 | **Week 4 · CI workflow from `init`** (PR `week-4/ci-workflow`): `.github/workflows/seamspec.yml` (`doctor --ci` then `verify --all --ci`; read-only token; never `pull_request_target`; toolchain steps chosen from runners and lockfiles; never overwritten); `init --ci/--no-ci` by mode (advisory never, enforced asks, strict always plus a CODEOWNERS block) | ADR-20261006-d16b |
| 2026-10-06 | **Full-run plan: condition E** (#31): the week-5 benchmark adds "rules written in `CLAUDE.md`" (no SeamSpec), to test whether SeamSpec's memory beats plain notes. The owner's decision | ADR-20261006-b270 |
| 2026-10-06 | **Week 4 · doctor** (#30): `seamspec doctor` (config, schemas naming the bad file, integrity, runner config, approval provenance, scopes; locally also the journal, CLAUDE.md block, pre-commit hook, allowlisted SeamSpec commands) and `doctor --ci`: rules only move forward (only by supersede, including tests re-hashed by an agent) plus a retirement summary in the job summary. This repo's CI runs it | ADR-20261006-9623 |
| 2026-10-06 | **Rough benchmark: PASS** (PR `week-3/bench-result`). Counted run of 24 runs on Sonnet 5.5, $27.40: V(A)=9, V(B)=1, V(C)=2, V(D)=6. SeamSpec beat plain tests on violations, tampering (0 vs 6) and dead ends (0 vs 4), at 1.29× the cost. In every T2 run with SeamSpec, the agent surfaced both conflicts with `request_supersede`; with plain tests it rewrote the tests. B ≈ C: the memory and the protocol do most of the work. Decision: keep building, and lead positioning with remembered agreements. Benchmark total about $42.69 | ADR-20261006-b270, `docs/benchmark/rough-1.md` |
| 2026-10-06 | **Benchmark calibration, part 2** (PR `week-3/bench-t2-conflicts`): the A-only check ($4.33) showed T1 breaking a rule in every run but T2 in none: Sonnet keeps behavior during refactors. T2's sessions 2–3 now bring conflicting requests from other teams (store credit below zero, a provider that rounds halves up), like T1's. The ADR adds a fairness note. Next: a T2-only A check (≈ $1.70) | ADR-20261006-c8b9 |
| 2026-10-06 | **Benchmark: stop on authentication errors** (PR `fix/bench-stop-on-auth-error`): the first calibration attempt hit a rejected API key ($0, about 3 minutes wasted per prompt). The harness now stops the batch at the first 401 or 403 | ADR-20261006-c8b9 |
| 2026-10-06 | **Benchmark trial + calibration** (#26): Sonnet trial (8 runs, 20 min, $8.88). Every part worked, but the verdict was "redo" (V(A)=1): the starting code restated its own rules. Templates no longer do; T2's temptations are stronger. Next: an A-only calibration check (4 runs, ≈ $4–5), then the counted run | ADR-20261006-c8b9 |
| 2026-10-06 | **Benchmark billing** (PR `week-3/bench-api-billing`): `--billing plan|api`. The owner switched to an API key, with Sonnet 5.5 for the trial run too. The harness checks Claude Code's reported `apiKeySource` on every prompt and stops on a mismatch | ADR-20261006-c8b9 |
| 2026-10-06 | **Benchmark harness built** (#24), no model calls yet: 2 task repos (Python job queue, TypeScript prices) with visible rule tests and hidden oracle tests, setup for conditions A–D, `claude -p` driver (fresh session per scripted session), scoring rules and the pass bar as code. `tests/test_bench.py` checks detectors, tampering, every verdict, the oracle, and full fake-agent runs | `bench/`, ADR-20261006-c8b9 |
| 2026-10-06 | **Benchmark plan accepted** (#23): 2 tasks, 3 fresh sessions per run (models forgetting), conditions A–D, hidden oracle tests; pass / change-the-pitch / kill thresholds fixed before any run; Claude Sonnet 5.5 on the owner's Pro plan in batches | ADR-20261006-c8b9 |
| 2026-10-06 | **Dogfooding** (#22): SeamSpec governs its own repo in **enforced** mode. The owner ran `init` (consent, plugin at local scope) and approved **6 LOCKED rules** in `seamspec review`; every commit now runs them in pre-commit. `docs/adr/` stays until agents have an ADR tool (v0.2). Fixed dogfooding findings: plugin prompt wording, `--proposed` repeatable-flag docs, "not found" error names the folder, approver identity matches git's, pre-commit hook skips branches without SeamSpec, scripted `init` no longer revokes consent, `.seamspec/.local/` ignored on every branch | ADR-20261006-0f6e |
| 2026-10-06 | **Setup friction, part 3: design** (PR `docs/chat-approvals-design`): approvals in chat through an MCP form dialog, with guards against hooks that could auto-answer it; a local review page is deferred to v0.2; typed approvals via `UserPromptSubmit` rejected. Hook risk verified in 5 Opus 5.5 sessions ($0.70): another plugin's or a mid-session settings hook can auto-approve; a `ConfigChange` hook blocks the mid-session case. **PROPOSED**: waiting for the owner's answers and verification 2 (dialog rendering) | ADR-20261006-c300 |
| 2026-10-05 | **Setup friction, part 2** (#20): this repo is also a plugin marketplace (`.claude-plugin/marketplace.json`); `seamspec init` shows the two `claude plugin` commands, asks, and installs the plugin at **local** scope (only `.claude/settings.local.json`, which it git-ignores); `--plugin` / `--no-plugin` for scripts. Checked against the real Claude Code CLI in a throwaway config | ADR-20261005-428a |
| 2026-10-05 | **Setup friction, part 1** (#19): test runs find the project's `.venv` / `venv` / `node_modules/.bin` tools without activation (an activated virtualenv wins); the plugin wrappers and pre-commit hook also look in `~/.local/bin` (desktop app, GUI git clients); a fresh clone's `init` asks one question covering consent and trust | ADR-20261005-9b8f |
| 2026-10-05 | **Week 3 · plugin** (PR `week-3/plugin`): `seamspec-plugin/` (hooks, MCP server, skills `/seamspec:lock` and `/seamspec:dead-end` generated from templates, wrappers in `scripts/`); `claude plugin validate` passes. **Verified in 3 real Claude Code sessions** (~$0.17 total): edit-time context reaches the model, the Stop gate blocked a regression 3× and the agent reverted, lock and dead-end skills work end to end. Try it: `claude --plugin-dir <repo>/seamspec-plugin` | ADR-20261005-5675 |
| 2026-10-05 | **Week 3 · MCP server** (PR `week-3/mcp`): `seamspec mcp` with 5 tools (`get_constraints`, `propose_invariant`, `log_dead_end`, `request_supersede`, `verify`) and 2 resources, on the MCP SDK 2.x; tested in-process and over stdio; ≈ 1,000 tokens of tool definitions | ADR-20261005-cc29 |
| 2026-10-05 | **Week 3 · hooks** (PR `week-3/hooks`): `seamspec hook claude pre-tool-use|stop` (`adapters/claude.py`, `core/session.py`, `tree_fingerprint`): ledger protection, edit-time context via `additionalContext`, Stop gate with deadline, per-prompt retries, supersede escape and journal check. Aligned with the current Claude Code hooks reference (no `stop_hook_active` any more). 246 tests | ADR-20261005-5009 |
| 2026-10-05 | The agent requests a Copilot review on every PR and addresses the findings before merge (automatic requests need GitHub Team) | ADR-20261005-c076 |
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

## Where we stand (2026-10-06, after the rough benchmark)

- **Works:** the core loop. A rule plus its test, human approval, then hooks and pre-commit block regressions; this repo's CI runs its own rules. Verified in real Claude Code sessions and dogfooded on this repo (#22).
- **Easier to set up** (#19, #20): no venv activation needed, one question on a teammate's clone, and `seamspec init` installs the plugin (local scope, asks first).
- **Proven, roughly:** the rough benchmark **passed** (ADR-20261006-b270):
  - **Fewer broken rules:** 2 with SeamSpec enforced, against 9 without it and 6 with plain tests.
  - **Every conflict surfaced:** with SeamSpec, the agent raised all 12 conflicts with old agreements through `request_supersede`.
  - **Plain tests got rewritten:** without SeamSpec's protection, the agent changed the tests to match the new behavior.
  - **The memory does most of the work:** advisory mode did as well as enforced mode.
- **Designed, not built:** approvals in chat (ADR-20261006-c300, PROPOSED).
- **Next, the owner decides the order:**
  1. **Week 4 onboarding:** the CI workflow from `init`, `doctor`, the remaining skills, and positioning copy that leads with remembered agreements.
  2. **Approvals in chat:** needs the owner's four answers and verification 2.
  3. **The full benchmark run in week 5:** a third task, ≥ 5 runs per cell, a second model, uncommitted pending changes reported separately, and **condition E: rules written in `CLAUDE.md`** (ADR-20261006-b270, decision 3).

## In progress

- **Week 4** (issue #4), slice by slice: `doctor` + `doctor --ci` (#30) → the CI workflow `init` installs → the remaining skills → mode handling → dogfooding on a real project.

## Next (Week 4, issue #4)

- [x] `seamspec doctor` (§16.5). Merged in #30
- [ ] CI workflow template from `init`: `doctor --ci` forward-only checks, `verify --all --ci`, retirement summary (§16.5). The checks are merged (#30); the template `init` installs is next
- [ ] Skills: `supersede`, `checkpoint`, `context`, `status` (§15A.2)
- [ ] `--mode advisory|enforced|strict` handling (§7.3)
- [ ] Dogfood on SeamSpec itself (done in #22) and at least one real project
- Exit criteria: CI blocks a regression and lists retirements on a test PR; `doctor` is clean on the fixtures

## Done in Week 3 (issue #3, closed)

- [x] Stop gate: deadline, retries, supersede escape, journal check (§16.1). Merged in #16
- [x] Edit-time context + ledger protection (§7.2). Merged in #16; confirmed in a real session (PR `week-3/plugin`)
- [x] MCP server: 5 tools + 2 resources (§14). Merged in #17
- [x] Plugin `seamspec-plugin/` + wrappers; skills `/seamspec:lock`, `/seamspec:dead-end` (§15A, §16.1). Merged in #18
- [x] Setup friction: project tools without activation, one question on a clone (#19); plugin install from `init` (#20); approvals in chat designed (ADR-20261006-c300, PROPOSED, #21; build deferred until after the benchmark unless the owner says otherwise)
- [x] Dogfood: `seamspec init` on this repo (enforced, 6 owner-approved rules, plugin enabled). `docs/adr/` stays for now (ADR-20261006-0f6e). #22
- [x] Rough benchmark A/B/C/D (§23); kill/pivot check as an ADR: **PASS** (ADR-20261006-b270). Plan **accepted** by the owner (ADR-20261006-c8b9, #23): pass bar fixed, Claude Sonnet 5.5, billed to an API key (owner's change). Harness built (#24). Trial done ($8.88, harness verdict "redo": tasks too easy). Calibrated (#26). Next: A-only calibration check, then the counted rough run

## Done in Week 2 (issue #2, closed)

- [x] `verifier` for pytest + vitest (§12.2, §19.7). Merged in #9
- [x] `lifecycle`: propose / approve / reject / supersede, journal, git identity (§11, §19.8). Merged in #10
- [x] `adr` module. Merged in #10
- [x] `review` with full test, red-green info and recent dead ends first (§11.4, §15). Merged in #14
- [x] `seamspec verify` CLI (`--all`, `--changed`, `--proposed`, `--gate`, `--ci`, `--json`). Merged in #11
- [x] Execution consent: `init` consent screen, `seamspec trust` (§12.4). Merged in #11
- [x] Pre-commit installer; `verify --gate` (§16.4). Merged in #11

## Open questions (owner's call)

- **Publishing to PyPI / npm:** waits for the owner's explicit go-ahead after thorough testing; no early pre-release (ADR-20261005-3adc). Try it meanwhile with `uv tool install --force --editable <path-to-repo>`.
- Before the repo goes public: remove references to the unpublished `Idea.md` from SPEC.md.
- **Proposal history on replace** (hands-on finding #7): `propose_invariant(replace_id=…)` overwrites the original rule text and origin. Keep the earlier version and show the diff in `seamspec review`?
- **Approvals in chat** (hands-on finding #8): design proposed in ADR-20261006-c300. Four questions for the owner there (option A now / B later, what's in scope, strict default, OK for verification runs).

## How to pick up this work

1. Read this file, then [`CLAUDE.md`](../CLAUDE.md) (working rules), then the current week's GitHub issue and SPEC §22.
2. `uv sync && npm ci --prefix tests/fixtures/ts_repo && uv run pytest && uv run ruff check . && uv run ruff format --check .` must pass before you start (without the npm install, the vitest tests skip).
3. Try the CLI in a scratch repo: `uv run --project <this repo> seamspec init`, then `seamspec status` / `seamspec context <file>`.
4. Work on a branch and open a PR (ADR-20261005-d8bc). Update this file **in the same PR as the code**; tick the week's issue boxes once the PR is merged.
