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
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

Attribution = tuple[set[str], set[str]]

MESSAGE_MAX = 200


@dataclass
class FailedCheck:
    """One way a rule's test failed, for the summary a human reads first (ADR-20261013-4e9b)."""

    line: int | None  # line in the rule's test file, when the report names one
    message: str  # the failure's first line, as the runner reported it
    cases: int = 1  # test cases that failed this way (a parametrized test fails once per case)


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


_STACK_LINE = re.compile(r"^\s*(❯|at)\s", re.MULTILINE)  # vitest / node stacks list the deepest frame first


def _line_in_harness(body: str, inv_id: str) -> int | None:
    """The line of the rule's own test file where the failure happened. Its path contains the rule's
    id (§12A.4). A pytest traceback ends at the failing line; a JavaScript stack starts with it."""
    found = re.findall(rf"[^\s:()]*{re.escape(inv_id)}[^\s:()]*:(\d+)", body)
    if not found:
        return None
    return int(found[0] if _STACK_LINE.search(body) else found[-1])


def _message(node: ET.Element) -> str:
    """The failure's first line. pytest reports a collection error as the bare words "collection
    failure" and keeps the reason (an ImportError, say) in the body's `E   ` lines."""
    first = next((ln.strip() for ln in (node.get("message") or "").splitlines() if ln.strip()), "")
    body = node.text or ""
    if not first or first == "collection failure":
        reasons = [ln[1:].strip() for ln in body.splitlines() if ln.startswith("E ") and ln[1:].strip()]
        first = (reasons[-1] if reasons else first) or next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    first = first or "failed (the runner's report gives no message)"
    return first if len(first) <= MESSAGE_MAX else first[: MESSAGE_MAX - 1].rstrip() + "…"


def junit_checks(report_path: Path, ids: list[str]) -> dict[str, list[FailedCheck]]:
    """What failed, per invariant, read from the same JUnit report as `junit()`. Identical failures
    (same line, same message) are counted, not repeated. Empty when the report is unusable: the
    caller then falls back to the runner's raw output."""
    try:
        tree = ET.parse(report_path)  # local file written by the runner SeamSpec just started
    except (OSError, ET.ParseError):
        return {}
    found: dict[str, dict[tuple[int | None, str], int]] = defaultdict(dict)
    for case in tree.iter("testcase"):
        where = " ".join(case.get(k, "") for k in ("file", "classname", "name"))
        for node in [*case.findall("failure"), *case.findall("error")]:
            for owner in (i for i in ids if i in where):
                key = (_line_in_harness(node.text or "", owner), _message(node))
                found[owner][key] = found[owner].get(key, 0) + 1
    return {
        owner: [FailedCheck(line, message, cases) for (line, message), cases in checks.items()]
        for owner, checks in found.items()
    }


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
