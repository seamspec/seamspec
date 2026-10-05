"""Per-invariant attribution from test reports (SPEC §12A.4).

Every harness path contains its invariant id, so a test case belongs to an invariant when that id
appears in the case's file / classname / name (JUnit) or package path (`go test -json`).

Each parser returns `(failed, empty)` or None when the report is unusable:
- `failed`: invariants with at least one failing or erroring case;
- `empty`: invariants that passed no test at all (nothing collected, or every test skipped).
  A harness passes only if it ran >= 1 test and passed >= 1 (§12.2).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

Attribution = tuple[set[str], set[str]]


def junit(report_path: Path, ids: list[str]) -> Attribution | None:
    if not report_path.is_file():
        return None
    try:
        tree = ET.parse(report_path)  # local file written by the runner SeamSpec just started
    except ET.ParseError:
        return None
    failed: set[str] = set()
    passed: dict[str, int] = defaultdict(int)
    for case in tree.iter("testcase"):
        where = " ".join(case.get(k, "") for k in ("file", "classname", "name"))
        owners = {i for i in ids if i in where}
        if case.find("failure") is not None or case.find("error") is not None:
            failed |= owners
        elif case.find("skipped") is None:
            for o in owners:
                passed[o] += 1
    empty = {i for i in ids if passed[i] == 0} - failed
    return failed, empty


def go_test_json(stdout: str, ids: list[str]) -> tuple[Attribution | None, str]:
    """Parse `go test -json`. Also returns plain-text output for the agent.
    A package with "no test files" or only skipped tests passes no test, so it lands in `empty`."""
    failed: set[str] = set()
    passed: dict[str, int] = defaultdict(int)
    text: list[str] = []
    any_event = False
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            text.append(line)  # build errors can be plain text
            continue
        if not isinstance(ev, dict):
            text.append(line)
            continue
        any_event = True
        owners = {i for i in ids if str(ev.get("Package", "")).endswith(i)}
        action = ev.get("Action")
        if action == "fail":
            failed |= owners
        elif action == "pass" and ev.get("Test"):
            for o in owners:
                passed[o] += 1
        elif action == "output":
            text.append(str(ev.get("Output", "")).rstrip("\n"))
    if not any_event:
        return None, "\n".join(text)
    return (failed, {i for i in ids if passed[i] == 0} - failed), "\n".join(text)
