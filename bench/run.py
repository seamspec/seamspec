"""Run the SeamSpec benchmark (ADR-20261006-c8b9).

    uv run python -m bench.run --tasks t1_queue --conditions A,B,C,D --runs 1 \\
        --model claude-haiku-4-5-20251001 --label dry-run            # prints the plan only
    ... --yes                                                          # actually runs Claude Code

Nothing calls Claude Code without --yes: every batch costs the owner (their plan's usage, or real
money with --billing api) and needs their go-ahead. With --billing api, set ANTHROPIC_API_KEY in
your own terminal and a spending limit in the Anthropic Console first.
Results go to bench/results/<label>/: results.jsonl (one line per run), summary.md, and logs/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .harness import score
from .harness.agent import BILLING, ClaudeAgent, FakeAgent, StopBatch
from .harness.prepare import CACHE, prepare
from .harness.tasks import CONDITION_NAMES, CONDITIONS, PASS_BAR_CONDITIONS, TASK_IDS, Task, load
from .harness.verdict import RunScore, _totals, b_vs_c_note, decide

RESULTS = Path(__file__).resolve().parent / "results"


def run_one(task: Task, condition: str, run: int, agent: ClaudeAgent | FakeAgent, out: Path) -> RunScore:
    work = CACHE / "runs" / out.name / f"{task.id}-{condition}-{run}"
    prepared = prepare(task, condition, work)
    cost, turns, errors = 0.0, 0, 0
    for s, prompts in enumerate(task.sessions, start=1):
        log = agent.run_session(work, s, prompts, condition in ("B", "C"),
                                out / "logs" / f"{task.id}-{condition}-{run}")  # fmt: skip
        cost += sum(r.cost_usd for r in log.results)
        turns += sum(r.turns for r in log.results)
        errors += sum(r.is_error for r in log.results)
    passed = score.oracle(task, work)
    landed = score.oracle(task, work, committed=True)
    return RunScore(
        task=task.id,
        condition=condition,
        run=run,
        violations={rule: not ok for rule, ok in passed.items()},
        tampering=score.tampering(work, prepared.rule_test_paths),
        dead_end=score.dead_end_reappeared(task, work),
        cost_usd=round(cost, 4),
        turns=turns,
        errors=errors,
        committed={rule: not ok for rule, ok in landed.items()},
    )


def summary(scores: list[RunScore], counted: bool) -> str:
    present = {s.condition for s in scores}
    verdict = decide(scores) if set(PASS_BAR_CONDITIONS) <= present else None
    lines = [
        "# Benchmark summary",
        "",
        "**Counted run.**" if counted else "**Dry run: checks the harness only. These numbers do not count.**",
        "",
        "| Task | Cond. | Run | Violations | Committed | Tampering | Dead end | Cost (est.) | Turns | Errors |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        broken = ", ".join(r for r, v in s.violations.items() if v) or "none"
        landed = "n/a" if s.committed is None else (", ".join(r for r, v in s.committed.items() if v) or "none")
        dead = "yes" if s.dead_end else "no"
        lines.append(f"| {s.task} | {s.condition} | {s.run} | {broken} | {landed} | {s.tampering} | {dead}"
                     f" | ${s.cost_usd:.2f} | {s.turns} | {s.errors} |")  # fmt: skip
    lines += ["", condition_table(scores)]
    if verdict is None:
        lines += ["", f"Pass bar not applied: it needs conditions {', '.join(PASS_BAR_CONDITIONS)} in one batch."]
    else:
        lines += ["", f"## Verdict: {verdict.title}", "", *[f"- {r}" for r in verdict.reasons],
                  f"- {b_vs_c_note(verdict)}"]  # fmt: skip
    return "\n".join(lines) + "\n"


def condition_table(scores: list[RunScore]) -> str:
    """Per condition: violations (working tree, the pass bar's metric) and violations committed at HEAD."""
    rows = ["| Condition | Runs | Violations | Committed | Tampering | Dead ends | Median cost |",
            "|---|---|---|---|---|---|---|"]  # fmt: skip
    for c in CONDITIONS:
        t = _totals(scores, c)
        if not t["runs"]:
            continue
        committed = "n/a" if t["committed"] != t["committed"] else f"{t['committed']:g}"  # NaN: not measured
        rows.append(f"| {c} · {CONDITION_NAMES[c]} | {t['runs']:g} | {t['violations']:g} | {committed}"
                    f" | {t['tampering']:g} | {t['dead_ends']:g} | ${t['median_cost']:.2f} |")  # fmt: skip
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.run", description=__doc__.split("\n")[1])
    ap.add_argument("--tasks", default=",".join(TASK_IDS))
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True, help="results folder name, e.g. dry-run or rough-batch-1")
    ap.add_argument("--budget-per-prompt", type=float, default=2.0, help="--max-budget-usd for each prompt")
    ap.add_argument("--counted", action="store_true", help="a counted run (the pass bar applies)")
    ap.add_argument(
        "--billing",
        choices=BILLING,
        default="plan",
        help="plan: Claude Code's own login (default); api: ANTHROPIC_API_KEY from this terminal",
    )
    ap.add_argument("--yes", action="store_true", help="really run Claude Code (costs the owner)")
    args = ap.parse_args(argv)

    tasks = [load(t) for t in args.tasks.split(",")]
    conditions = [c.strip().upper() for c in args.conditions.split(",")]
    jobs = [(task, c, r) for r in range(1, args.runs + 1) for task in tasks for c in conditions]
    prompts = sum(len(s) for task in tasks for s in task.sessions) * len(conditions) * args.runs
    print(f"Plan: {len(jobs)} runs ({', '.join(t.id for t in tasks)} x {', '.join(conditions)} x {args.runs}), "
          f"{prompts} prompts on {args.model}, at most ${args.budget_per_prompt:g} per prompt.")  # fmt: skip
    api = "API key (real charges; set a spending limit in the Anthropic Console)"
    print("Billing: " + (api if args.billing == "api" else "Claude Code's login (your plan's usage)"))
    if not args.yes:
        print("Nothing run. Add --yes once the owner has approved this batch.")
        return 0

    try:
        agent = ClaudeAgent(args.model, args.budget_per_prompt, args.billing)
    except StopBatch as exc:
        print(f"Not started: {exc}")
        return 2
    out = RESULTS / args.label
    out.mkdir(parents=True, exist_ok=True)
    scores: list[RunScore] = []
    with (out / "results.jsonl").open("a", encoding="utf-8") as f:
        for task, condition, run in jobs:
            started = time.monotonic()
            try:
                s = run_one(task, condition, run, agent, out)
            except StopBatch as exc:
                print(f"Stopped: {exc}")
                break
            scores.append(s)
            record = {**asdict(s), "model": args.model, "billing": args.billing,
                      "seconds": round(time.monotonic() - started)}  # fmt: skip
            f.write(json.dumps(record) + "\n")
            f.flush()
            print(f"{task.id} {condition} run {run}: {s.violation_count} violation(s), tampering {s.tampering}, "
                  f"dead end {'yes' if s.dead_end else 'no'}, ${s.cost_usd:.2f}", flush=True)  # fmt: skip
    if not scores:
        return 2
    (out / "summary.md").write_text(summary(scores, args.counted), encoding="utf-8")
    print(f"Summary: {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
