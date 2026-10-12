"""Export customer records (one JSON object per line) to CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import IO, Any

COLUMNS = ["id", "name", "email", "amount_cents"]


class BadRecord(ValueError):
    """A record that can't be turned into a CSV row."""


def to_row(record: Any) -> list[str]:
    if not isinstance(record, dict):
        raise BadRecord("not an object")
    try:
        return [
            str(record["id"]),
            str(record["name"]),
            str(record["email"]),
            str(int(record["amount_cents"])),
        ]
    except KeyError as exc:
        raise BadRecord(f"missing field {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise BadRecord(f"bad amount_cents: {exc}") from exc


def export(lines: IO[str], out: IO[str], err: IO[str]) -> int:
    """Write one CSV row per record; return how many records could not be written."""
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    skipped = 0
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            writer.writerow(to_row(json.loads(line)))
        except (json.JSONDecodeError, BadRecord) as exc:
            skipped += 1
            print(f"line {number}: {exc}", file=err)
    return skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exportcli", description=__doc__)
    parser.add_argument("input", help="JSON Lines file with customer records")
    parser.add_argument("-o", "--output", help="write the CSV to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = open(args.input, encoding="utf-8")  # noqa: SIM115 - closed below
    except OSError as exc:
        print(f"exportcli: {exc}", file=sys.stderr)
        return 2
    with source:
        if args.output:
            with open(args.output, "w", encoding="utf-8", newline="") as out:
                skipped = export(source, out, sys.stderr)
        else:
            skipped = export(source, sys.stdout, sys.stderr)
    return 1 if skipped else 0
