"""Compare a batch with an earlier one, e.g. condition E with the rough run (ADR-20261007-e1a7).

    uv run python -m bench.compare --base rough-1 --with rough-1e

Runs recorded before "committed" was measured get it computed from their cached working copies
(`~/.cache/seamspec-bench/runs/<label>/`), when those still exist. Nothing calls a model.
"""

from __future__ import annotations

import argparse
import json
import sys

from .harness import prepare, score
from .harness.tasks import load
from .harness.verdict import RunScore, _totals, read_condition_e
from .run import RESULTS, condition_table


def load_scores(label: str) -> list[RunScore]:
    fields = set(RunScore.__dataclass_fields__)
    out = []
    for line in (RESULTS / label / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            out.append(RunScore(**{k: v for k, v in data.items() if k in fields}))
    return out


def fill_committed(label: str, scores: list[RunScore]) -> None:
    """Measure 'committed' for older runs from their cached working copies."""
    for s in scores:
        work = prepare.CACHE / "runs" / label / f"{s.task}-{s.condition}-{s.run}"
        if s.committed is None and (work / ".git").is_dir():
            s.committed = {rule: not ok for rule, ok in score.oracle(load(s.task), work, committed=True).items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.compare", description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="results label of the earlier batch, e.g. rough-1")
    ap.add_argument("--with", dest="other", required=True, help="results label of the new batch, e.g. rough-1e")
    args = ap.parse_args(argv)
    base, other = load_scores(args.base), load_scores(args.other)
    fill_committed(args.base, base)
    fill_committed(args.other, other)
    scores = base + other
    print(f"# {args.base} + {args.other}\n")
    print(condition_table(scores))
    c, e = _totals(scores, "C"), _totals(scores, "E")
    if c["runs"] and e["runs"]:
        code, text = read_condition_e(c["violations"], e["violations"])
        print(f"\n## Condition E: {text}\n")
        print(f"- V(C) = {c['violations']:g}, V(E) = {e['violations']:g} (reading rule fixed in ADR-20261007-e1a7)")
        print(f"- Committed (secondary, not decisive): C = {c['committed']:g}, E = {e['committed']:g}")
        print(f"- reading: {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
