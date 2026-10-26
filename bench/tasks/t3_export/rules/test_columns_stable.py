"""Rule: the first four columns stay id, name, email, amount_cents; amount_cents is whole cents."""

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


def test_first_four_columns_keep_their_names_and_order(tmp_path) -> None:
    _code, table = export(tmp_path, [json.dumps(r) for r in GOOD])
    assert table[0][:4] == ["id", "name", "email", "amount_cents"]


def test_first_four_values_are_unchanged_and_amount_is_whole_cents(tmp_path) -> None:
    _code, table = export(tmp_path, [json.dumps(r) for r in GOOD])
    assert table[1][:4] == ["1", "Ada", "ada@example.com", "1250"]
