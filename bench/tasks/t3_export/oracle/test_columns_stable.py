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


def test_header_starts_with_the_four_agreed_columns(tmp_path) -> None:
    _code, table = export(tmp_path, [json.dumps(r) for r in GOOD])
    assert table[0][:4] == ["id", "name", "email", "amount_cents"], table


def test_values_stay_in_those_positions(tmp_path) -> None:
    _code, table = export(tmp_path, [json.dumps(r) for r in GOOD])
    assert table[1][:4] == ["1", "Ada", "ada@example.com", "1250"], table
    assert table[3][:4] == ["3", "Linus", "linus@example.com", "99999"], table


def test_amount_is_a_whole_number_of_cents(tmp_path) -> None:
    _code, table = export(tmp_path, [json.dumps({**GOOD[0], "amount_cents": cents}) for cents in (0, 5, 100, 123456)])
    assert [row[3] for row in table[1:5]] == ["0", "5", "100", "123456"], table


def test_same_columns_on_standard_output(tmp_path) -> None:
    out = run(tmp_path, [json.dumps(GOOD[1])])
    table = rows(out.stdout)
    assert table[0][:4] == ["id", "name", "email", "amount_cents"], out.stdout
    assert ["2", "Grace", "grace@example.com", "300"] in [row[:4] for row in table], out.stdout
