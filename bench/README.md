# SeamSpec benchmark

Do agents break fewer agreed behaviors with SeamSpec than without? Design, scoring and the pass bar are in [ADR-20261006-c8b9](../docs/adr/ADR-20261006-c8b9-rough-benchmark-plan-and-pass-bar.md); they were fixed before any run.

| Folder | What |
|---|---|
| `tasks/<id>/template/` | The repo the agent works on |
| `tasks/<id>/task.json` | Rules, the known dead end, and 3 sessions of prompts |
| `tasks/<id>/rules/` | Visible rule tests (enforced in conditions B, C, D) |
| `tasks/<id>/oracle/` | Hidden tests that score every condition; the agent never sees them |
| `harness/` | Setup per condition, the agent driver, scoring, and the pass bar as code |
| `results/` | Local output (git-ignored): `results.jsonl`, `summary.md`, raw session logs |

Conditions:
- **A:** nothing;
- **B:** SeamSpec advisory;
- **C:** SeamSpec enforced;
- **D:** the same rule tests plus a plain Stop hook (no SeamSpec);
- **E:** the same rules and dead end as plain notes in `CLAUDE.md` (ADR-20261007-e1a7).

Every run is scored on the final working tree (the pass bar's metric), and also on what was **committed** at `HEAD`. To compare a batch with an earlier one (no model calls):

```bash
uv run python -m bench.compare --base rough-1 --with rough-1e
```

```bash
uv run python -m bench.run --tasks t1_queue,t2_prices --runs 1 --model claude-haiku-4-5-20251001 --label dry-run
```

That prints the plan and runs nothing. Add `--yes` only after the owner approves the batch. Add `--counted` for runs the pass bar applies to.

**Billing** (`--billing`, the owner's choice):
- `plan` (default): Claude Code's own login. The harness removes `ANTHROPIC_API_KEY`.
- `api`: real charges to an Anthropic API key. Set a spending limit in the Anthropic Console, then set the key **in your own terminal** and run the command there. The key is never written to a file.

Either way, the harness checks the `apiKeySource` Claude Code reports on every prompt, and stops if it doesn't match.

- **Isolation:** working copies live under `~/.cache/seamspec-bench/runs/`, outside this repo. Each run gets a fresh git repo, its own `.venv` (T1) or a link to a pinned vitest install (T2).
- **Settings:** Claude Code runs with `--setting-sources project,local`, so the owner's own plugins and hooks don't affect results.
- **Tests:** `tests/test_bench.py` checks the detectors, tampering counts, every pass-bar verdict, the oracle on clean and broken code, and full runs with a scripted fake agent. No model is called.
