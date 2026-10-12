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


def test_standard_output_is_only_the_csv(tmp_path) -> None:
    out = run(tmp_path, [json.dumps(r) for r in GOOD])
    assert [row[0] for row in rows(out.stdout)] == ["id", "1", "2", "3"]


def test_a_skipped_record_is_reported_on_standard_error(tmp_path) -> None:
    out = run(tmp_path, [json.dumps(GOOD[0]), "not json", json.dumps(GOOD[1])])
    assert [row[0] for row in rows(out.stdout)] == ["id", "1", "2"]
    assert out.stderr.strip()
