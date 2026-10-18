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

from .harness import capture, score
from .harness.agent import BILLING, ClaudeAgent, FakeAgent, StopBatch
from .harness.prepare import CACHE, prepare
from .harness.tasks import CONDITION_NAMES, CONDITIONS, PASS_BAR_CONDITIONS, TASK_IDS, USES_PLUGIN, Task, load
from .harness.verdict import (
    CLAIMS,
    STUDY_CLAIMS,
    RunScore,
    _totals,
    b_vs_c_note,
    decide,
    decide_capture,
    decide_full,
    decide_long,
)

RESULTS = Path(__file__).resolve().parent / "results"


def run_one(task: Task, condition: str, run: int, agent: ClaudeAgent | FakeAgent, out: Path,
            shape: str = "sessions") -> RunScore:  # fmt: skip
    """`shape`: "sessions" (the task's three sessions) or "long" (one session with unrelated requests
    between the agreement and the temptations, ADR-20261015-c8e1)."""
    work = CACHE / "runs" / out.name / f"{task.id}-{condition}-{run}"
    prepared = prepare(task, condition, work)
    logs = out / "logs" / f"{task.id}-{condition}-{run}"
    sessions = (task.long_session(),) if shape == "long" else task.sessions
    cost, turns, errors = 0.0, 0, 0
    extra: dict = {}
    for s, prompts in enumerate(sessions, start=1):
        log = agent.run_session(work, s, prompts, condition in USES_PLUGIN, logs)
        cost += sum(r.cost_usd for r in log.results)
        turns += sum(r.turns for r in log.results)
        errors += sum(r.is_error for r in log.results)
        if condition == "S" and s < len(sessions):  # the person reviews between sessions
            extra.setdefault("approved", []).extend(capture.review(work).approved)
            if s == 1:
                extra["captured"], extra["captured_dead_end"] = capture.captured(task, work)
        if condition == "N" and s == 1:
            extra["notes"], _ = capture.notes_mentions(task, work)
    if shape == "long":
        extra["gate_catches"], extra["compacted"] = score.gate_catches(logs), score.compacted(logs)
    passed = score.oracle(task, work)
    landed = score.oracle(task, work, committed=True)
    tampered = score.tampering(work, prepared.rule_test_paths) + (
        capture.locked_tampered(work) if condition == "S" else 0
    )
    return RunScore(
        task=task.id,
        condition=condition,
        run=run,
        violations={rule: not ok for rule, ok in passed.items()},
        tampering=tampered,
        dead_end=score.dead_end_reappeared(task, work),
        cost_usd=round(cost, 4),
        turns=turns,
        errors=errors,
        committed={rule: not ok for rule, ok in landed.items()},
        **extra,
    )


def summary(scores: list[RunScore], counted: bool, bar: str = "rough", baseline: list[RunScore] | None = None) -> str:
    """`bar`: which pass bar to apply when A-D are all present: the rough run's (ADR-20261006-c8b9),
    the full run's (ADR-20261013-9d41), or none (a second model: reported, never judged). `capture`
    and `long` apply ADR-20261015-c8e1's bars; capture compares with `baseline` (an earlier batch's A and E)."""
    present = {s.condition for s in scores}
    complete = set(PASS_BAR_CONDITIONS) <= present and bar not in ("none", "capture", "long")
    verdict = (decide_full(scores) if bar == "full" else decide(scores)) if complete else None
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
    if bar in ("capture", "long"):
        return "\n".join(lines + ["", *study_section(scores, bar, baseline or [])]) + "\n"
    if bar == "none":
        lines += ["", "No pass bar applies to this batch: it is reported, not judged."]
    elif verdict is None:
        lines += ["", f"Pass bar not applied: it needs conditions {', '.join(PASS_BAR_CONDITIONS)} in one batch."]
    elif bar == "full":
        lines += ["", f"## Verdict: {verdict.title}", "", *[f"- {r}" for r in verdict.reasons], "",
                  "## What the write-up may claim", "",
                  *[f"- {'yes' if ok else 'NO '}: {CLAIMS[name]}" for name, ok in verdict.claims.items()]]  # fmt: skip
    else:
        lines += ["", f"## Verdict: {verdict.title}", "", *[f"- {r}" for r in verdict.reasons],
                  f"- {b_vs_c_note(verdict)}"]  # fmt: skip
    return "\n".join(lines) + "\n"


def study_section(scores: list[RunScore], bar: str, baseline: list[RunScore]) -> list[str]:
    """The capture or long-session details, then its verdict and what the write-up may claim."""
    lines: list[str] = []
    if bar == "capture":
        lines += ["## Capture by run", "",
                  "| Task | Cond. | Run | Captured (rules) | Dead end | Approved | Notes mention |",
                  "|---|---|---|---|---|---|---|"]  # fmt: skip
        for s in scores:
            got = ", ".join(r for r, ok in (s.captured or {}).items() if ok) or (
                "none" if s.captured is not None else "n/a"
            )
            dead = "n/a" if s.captured_dead_end is None else ("yes" if s.captured_dead_end else "no")
            notes = ", ".join(r for r, ok in (s.notes or {}).items() if ok) or (
                "none" if s.notes is not None else "n/a"
            )
            lines.append(f"| {s.task} | {s.condition} | {s.run} | {got} | {dead} | {len(s.approved or [])} | {notes} |")
        verdict = decide_capture(scores, baseline)
        names = ("captures", "beats_self_notes")
    else:
        lines += ["## Long session by run", "", "| Task | Cond. | Run | Violations | Gate catches | Compacted |",
                  "|---|---|---|---|---|---|"]  # fmt: skip
        for s in scores:
            lines.append(f"| {s.task} | {s.condition} | {s.run} | {s.violation_count} | {s.gate_catches} | "
                         f"{'yes' if s.compacted else 'no'} |")  # fmt: skip
        verdict = decide_long(scores)
        names = ("gate_catches_forgetting",)
    lines += ["", f"## Verdict: {verdict.title}", "", *[f"- {r}" for r in verdict.reasons], "",
              "## What the write-up may claim", "",
              *[f"- {'yes' if verdict.claims.get(n) else 'NO '}: {STUDY_CLAIMS[n]}" for n in names]]  # fmt: skip
    return lines


def finished(path: Path) -> list[RunScore]:
    """Runs already scored in this batch's results.jsonl: a long batch that stopped can go on."""
    if not path.is_file():
        return []
    fields = set(RunScore.__dataclass_fields__)
    done = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            done.append(RunScore(**{k: record[k] for k in fields if k in record}))
    return done


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
    ap.add_argument("--bar", choices=("rough", "full", "none", "capture", "long"), default="rough",
                    help="which pass bar the summary applies: rough (c8b9), full (9d41), capture or long (c8e1), "
                         "or none")  # fmt: skip
    ap.add_argument(
        "--shape",
        choices=("sessions", "long"),
        default="sessions",
        help="sessions: the task's three sessions; long: one session with unrelated requests in between",
    )
    ap.add_argument("--baseline", help="for --bar capture: the earlier batch whose A and E runs are compared")
    ap.add_argument("--resume", action="store_true",
                    help="skip runs this label's results.jsonl already holds, and summarize them all")  # fmt: skip
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
    baseline: list[RunScore] = []
    if args.bar == "capture":
        if not args.baseline:
            print("--bar capture needs --baseline <label> (the batch whose A and E runs are compared, e.g. full-1).")
            return 2
        baseline = finished(RESULTS / args.baseline / "results.jsonl")
        if not baseline:
            print(f"No results in {RESULTS / args.baseline / 'results.jsonl'}: nothing to compare with.")
            return 2
    jobs = [(task, c, r) for r in range(1, args.runs + 1) for task in tasks for c in conditions]
    per_task = {
        t.id: (len(t.long_session()) if args.shape == "long" else sum(len(s) for s in t.sessions)) for t in tasks
    }
    prompts = sum(per_task.values()) * len(conditions) * args.runs
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
    scores: list[RunScore] = finished(out / "results.jsonl") if args.resume else []
    have = {(s.task, s.condition, s.run) for s in scores}
    if have:
        print(f"Resuming: {len(have)} run(s) already scored in {out / 'results.jsonl'}.")
    with (out / "results.jsonl").open("a", encoding="utf-8") as f:
        for task, condition, run in jobs:
            if (task.id, condition, run) in have:
                continue
            started = time.monotonic()
            try:
                s = run_one(task, condition, run, agent, out, args.shape)
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
    (out / "summary.md").write_text(summary(scores, args.counted, args.bar, baseline), encoding="utf-8")
    print(f"Summary: {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
