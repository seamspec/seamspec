"""Rule: exit code 0 only when every record was exported, 1 when any was skipped, 2 for a usage error."""

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

SRC = next(p / "src" for p in Path(__file__).resolve().parents if (p / "src/exportcli").is_dir())
GOOD = [
    {"id": 1, "name": "Ada", "email": "ada@example.com", "amount_cents": 1250, "country": "GB"},
    {"id": 2, "name": "Grace", "email": "grace@example.com", "amount_cents": 300, "country": "US"},
    {"id": 3, "name": "Linus", "email": "linus@example.com", "amount_cents": 99999, "country": "FI"},
]


def run(tmp_path, lines, *args):
    """Run the tool the way cron does: `python -m exportcli INPUT`, CSV on standard output."""
    source = tmp_path / "customers.jsonl"
    source.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "exportcli", str(source), *args], capture_output=True, text=True, env=env, timeout=60
    )


def rows(text):
    return list(csv.reader(io.StringIO(text)))


def export(tmp_path, lines):
    """Export to a file with -o, so these checks don't depend on what else is printed: (exit code, rows)."""
    target = tmp_path / "out.csv"
    out = run(tmp_path, lines, "-o", str(target))
    return out.returncode, rows(target.read_text(encoding="utf-8")) if target.exists() else []


def test_0_when_every_record_was_exported(tmp_path) -> None:
    assert export(tmp_path, [json.dumps(r) for r in GOOD])[0] == 0
    assert export(tmp_path, [])[0] == 0


def test_1_for_each_kind_of_skipped_record(tmp_path) -> None:
    bad = ["not json", json.dumps({"id": 8, "name": "No amount", "email": "x@example.com"}), json.dumps([1, 2]),
           json.dumps({"id": 9, "name": "N", "email": "e@example.com", "amount_cents": "twelve"})]  # fmt: skip
    for line in bad:
        code, table = export(tmp_path, [json.dumps(GOOD[0]), line, json.dumps(GOOD[1])])
        assert code == 1, f"{line!r} gave exit code {code}"
        assert [row[0] for row in table[1:]] == ["1", "2"], table  # the good records are still exported


def test_1_even_when_only_one_record_in_many_is_bad(tmp_path) -> None:
    lines = [json.dumps({**GOOD[0], "id": n}) for n in range(1, 201)]
    lines.insert(137, "{broken")
    assert export(tmp_path, lines)[0] == 1


def test_1_when_a_record_is_skipped_and_the_csv_goes_to_standard_output(tmp_path) -> None:
    assert run(tmp_path, [json.dumps(GOOD[0]), "not json"]).returncode == 1


def test_2_for_usage_errors(tmp_path) -> None:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    missing = subprocess.run(
        [sys.executable, "-m", "exportcli", str(tmp_path / "nope.jsonl")], capture_output=True, text=True, env=env
    )
    no_args = subprocess.run([sys.executable, "-m", "exportcli"], capture_output=True, text=True, env=env)
    assert missing.returncode == 2 and no_args.returncode == 2
