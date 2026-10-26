"""Rule: when the CSV goes to standard output, nothing else is written there."""

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


BAD = ["not json", json.dumps({"id": 8, "name": "No amount", "email": "x@example.com"}), json.dumps([1, 2])]


def test_only_csv_rows_on_standard_output_when_all_records_are_good(tmp_path) -> None:
    out = run(tmp_path, [json.dumps(r) for r in GOOD])
    assert [row[0] for row in rows(out.stdout)] == ["id", "1", "2", "3"], out.stdout


def test_only_csv_rows_on_standard_output_when_records_are_skipped(tmp_path) -> None:
    lines = [json.dumps(GOOD[0]), BAD[0], json.dumps(GOOD[1]), BAD[1], BAD[2], json.dumps(GOOD[2])]
    out = run(tmp_path, lines)
    assert [row[0] for row in rows(out.stdout)] == ["id", "1", "2", "3"], out.stdout


def test_only_the_header_on_standard_output_for_an_empty_input(tmp_path) -> None:
    out = run(tmp_path, [])
    assert [row[0] for row in rows(out.stdout)] == ["id"], out.stdout


def test_every_line_on_standard_output_has_the_header_width(tmp_path) -> None:
    out = run(tmp_path, [json.dumps(r) for r in GOOD] + BAD)
    table = rows(out.stdout)
    assert table and all(len(row) == len(table[0]) for row in table), out.stdout
