# SeamSpec benchmark

Do agents break fewer agreed behaviors with SeamSpec than without? Design, scoring and the pass bar are in [ADR-20261006-c8b9](../docs/adr/ADR-20261006-c8b9-rough-benchmark-plan-and-pass-bar.md) (rough run) and [ADR-20261013-9d41](../docs/adr/ADR-20261013-9d41-full-benchmark-plan-and-pass-bar.md) (full run); each was fixed before its run.

Tasks: `t1_queue` (Python job queue), `t2_prices` (TypeScript price calculator), `t3_export` (Python command-line export tool).

| Folder | What |
|---|---|
| `tasks/<id>/template/` | The repo the agent works on |
| `tasks/<id>/task.json` | Rules, the known dead end, 3 sessions of prompts, and the other decision records of condition F (`adr_noise`) |
| `tasks/<id>/rules/` | Visible rule tests (enforced in conditions B, C, D) |
| `tasks/<id>/oracle/` | Hidden tests that score every condition; the agent never sees them |
| `harness/` | Setup per condition, the agent driver, scoring, and the pass bar as code |
| `results/` | Local output (git-ignored): `results.jsonl`, `summary.md`, raw session logs |

Conditions:
- **A:** nothing;
- **B:** SeamSpec advisory;
- **C:** SeamSpec enforced;
- **D:** the same rule tests plus a plain Stop hook (no SeamSpec);
- **E:** the same rules and dead end as plain notes in `CLAUDE.md` (ADR-20261007-e1a7);
- **F:** the same decisions as records in `docs/adr/`, among unrelated and outdated ones, with nothing pointing at them (ADR-20261013-9d41);
- **G and H:** E and C again with **36 more agreed rules** about two helper packages (`scale/`, `harness/scale.py`). Only the task's own rules are scored: do they still hold as three among thirty-nine?
- **N and S** (the capture benchmark, [ADR-20261015-c8e1](../docs/adr/ADR-20261015-c8e1-capture-and-long-session-benchmarks.md)): nothing is written down; the agreements exist only in session 1's prompt.
  - **N:** one `CLAUDE.md` line asks the agent to keep its own NOTES.md.
  - **S:** SeamSpec enforced with an **empty** ledger. Between sessions a scripted person approves every proposed rule whose test passes (`harness/capture.py`). After session 1, an agreement counts as **captured** when a locked rule test passes on the starting code and fails on that agreement's violating patch (`task.json` → `capture.mutants`).

**The long shape** (`--shape long`, the long-session benchmark): a task's three sessions run as **one**, with the 12 unrelated requests of `task.json` → `fillers` between the agreement and the temptations. It reports how often SeamSpec's Stop or commit check sent the agent back (from the session logs) and whether Claude Code compacted the conversation.

Every run is scored on the final working tree (the pass bar's metric), and also on what was **committed** at `HEAD`. To compare a batch with an earlier one (no model calls):

```bash
uv run python -m bench.compare --base rough-1 --with rough-1e
```

```bash
uv run python -m bench.run --tasks t1_queue,t2_prices --runs 1 --model claude-haiku-4-5-20251001 --label dry-run
```

That prints the plan and runs nothing. Add `--yes` only after the owner approves the batch. Add `--counted` for runs the pass bar applies to.

- `--bar rough|full|none` chooses the pass bar the summary applies (default `rough`). `full` also prints which claims the write-up may make. `none` is for a second model: reported, never judged.
- `--resume` continues a batch that stopped: runs already in that label's `results.jsonl` are kept and not run again.

The full run, once the owner has accepted ADR-20261013-9d41 (each line is a separate, paid batch; run them in your own terminal with the key set). `--conditions` defaults to every setup, N and S included, so the full run names A–H: without it, it would be 150 runs, not 120:

```bash
uv run python -m bench.run --tasks t3_export --conditions A --runs 2 --model claude-sonnet-5-5 --label calib-t3 --billing api --yes
uv run python -m bench.run --conditions A,B,C,D,E,F,G,H --runs 5 --model claude-sonnet-5-5 --label full-1 --billing api --counted --bar full --resume --yes   # 120 runs
uv run python -m bench.run --conditions A,C,D,E --runs 3 --model claude-haiku-5-5 --label full-1-haiku --billing api --bar none --resume --yes
```

The capture and long-session benchmarks (ADR-20261015-c8e1, accepted 2026-10-18; about $125-160 in all). Calibrate first (about $6), check the logs, then run the counted batches:

```bash
uv run python -m bench.run --tasks t1_queue --conditions S --runs 1 --model claude-sonnet-5-5 --label calib-capture --billing api --bar none --yes
uv run python -m bench.run --tasks t1_queue --conditions A --runs 1 --model claude-sonnet-5-5 --label calib-long --billing api --shape long --bar none --yes
uv run python -m bench.run --conditions N,S --runs 5 --model claude-sonnet-5-5 --label capture-1 --billing api --counted --bar capture --baseline full-1 --resume --yes   # 30 runs
uv run python -m bench.run --conditions A,E,C --runs 3 --model claude-sonnet-5-5 --label long-1 --billing api --counted --shape long --bar long --resume --yes   # 27 runs
```

`--bar capture` compares with `--baseline full-1`: that batch's A (nothing) and E (hand-written notes) ran the same prompts.

**The second-actor benchmark** (`--shape second`, [ADR-20261019-5f3b](../docs/adr/ADR-20261019-5f3b-second-actor-benchmark-plan.md), accepted 2026-10-19; about $16-20):
- the author's session 1 is pushed to a local bare repository;
- a teammate's fresh clone (no hooks, no local SeamSpec state, no plugin) gets sessions 2 and 3 as one session, then pushes;
- "CI" runs locally on what landed: the project's tests, plus `seamspec verify --all --ci` where SeamSpec is set up;
- each run also pushes every agreement's violating patch by hand, as a demonstration (`harness/second.py`).

```bash
uv run python -m bench.run --tasks t1_queue --conditions N,S --runs 1 --model claude-sonnet-5-5 --label calib-second --billing api --shape second --bar none --yes
uv run python -m bench.run --conditions A,E,N,S --runs 3 --model claude-sonnet-5-5 --label second-1 --billing api --counted --shape second --bar second --resume --yes   # 36 runs
```

**Billing** (`--billing`, the owner's choice):
- `plan` (default): Claude Code's own login. The harness removes `ANTHROPIC_API_KEY`.
- `api`: real charges to an Anthropic API key. Set a spending limit in the Anthropic Console, then set the key **in your own terminal** and run the command there. The key is never written to a file.

Either way, the harness checks the `apiKeySource` Claude Code reports on every prompt, and stops if it doesn't match.

- **Isolation:** working copies live under `~/.cache/seamspec-bench/runs/`, outside this repo. Each run gets a fresh git repo, its own `.venv` (T1) or a link to a pinned vitest install (T2).
- **Settings:** Claude Code runs with `--setting-sources project,local`, so the owner's own plugins and hooks don't affect results.
- **Tests:** `tests/test_bench.py` checks the detectors, tampering counts, every pass-bar verdict, the oracle on clean and broken code, and full runs with a scripted fake agent. No model is called.
