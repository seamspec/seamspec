"""The summary a human reads when a rule fails (SPEC §12A.4, ADR-20261013-4e9b).

Dogfooding finding #11: the first time SeamSpec refused a commit, the owner got about 80 lines of
raw pytest output for a one-line problem. The rule's title never appeared (only its id), the same
failure was printed once per test case, and the line that mattered was in the middle.

So every failure report leads with one short block per failing rule: its id and title, the check
that failed (the line of its test file, read from disk) and what the runner said. It is built from
the ledger and the runner's JUnit report, never from parsing terminal output. When the report can't
say what failed (a timeout, an unreadable report, a group nobody could attribute), the rule is
listed with that reason and its raw output is still shown: a summary must never hide a failure.
"""

from __future__ import annotations

from pathlib import Path

from .models import Invariant
from .reports import FailedCheck
from .store import RecordError, Store
from .verifier import RunnerResult, VerifyReport

SOURCE_MAX = 110


def _invariant(store: Store, inv_id: str) -> Invariant | None:
    try:
        record = store.get(inv_id)
    except (KeyError, RecordError, ValueError):  # a missing or broken record must not hide the failure reported
        return None
    return record if isinstance(record, Invariant) else None


def _source_line(root: Path, inv: Invariant | None, line: int | None) -> str:
    """The text of `line` in the rule's test file: the check itself, as written."""
    if inv is None or line is None:
        return ""
    try:
        lines = (root / inv.verification.harness_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    text = " ".join(lines[line - 1].split()) if 0 < line <= len(lines) else ""
    return text if len(text) <= SOURCE_MAX else text[: SOURCE_MAX - 1].rstrip() + "…"


def _check_lines(root: Path, inv: Invariant | None, check: FailedCheck) -> list[str]:
    cases = f"  ({check.cases} test cases)" if check.cases > 1 else ""
    source = _source_line(root, inv, check.line)
    if check.line is None:
        return [f"    {check.message}{cases}"]
    if not source:
        return [f"    line {check.line}: {check.message}{cases}"]
    return [f"    line {check.line}: {source}", f"      {check.message}{cases}"]


def _rule(store: Store, inv_id: str, body: list[str]) -> list[str]:
    inv = _invariant(store, inv_id)
    out = ["", f"  {inv_id} · {inv.title}" if inv else f"  {inv_id}", *body]
    if inv:
        out.append(f"    Test: {inv.verification.harness_path}")
    return out


def _why_unexplained(result: RunnerResult) -> str:
    if result.incomplete:
        return "not checked: time ran out"
    if result.timed_out:
        return "its test timed out"
    if result.could_not_run:
        return "its test could not be started"
    if result.failed_ids is None and len(result.invariant_ids) > 1:
        return f"one or more of these {len(result.invariant_ids)} rules failed; the runner's report doesn't say which"
    return "failed; the runner's report doesn't say where"


def summary(store: Store, report: VerifyReport) -> tuple[list[str], list[RunnerResult]]:
    """The summary lines, and the failing results the summary could not explain: their raw output
    has to be shown as well."""
    lines: list[str] = []
    for failure in report.integrity_failures:  # "inv_x: harness modified since approval"
        inv_id, _, what = failure.partition(": ")
        lines += _rule(store, inv_id, [f"    {what}"])
    unexplained: list[RunnerResult] = []
    for result in report.results:
        if result.passed:
            continue
        ids = result.failed_ids if result.failed_ids is not None else result.invariant_ids
        explained = bool(ids) and all(result.checks.get(i) for i in ids)
        if not explained:
            unexplained.append(result)
        for inv_id in ids:
            checks = result.checks.get(inv_id)
            inv = _invariant(store, inv_id)
            body = (
                [ln for check in checks for ln in _check_lines(store.root, inv, check)]
                if checks
                else [f"    {_why_unexplained(result)}"]
            )
            lines += _rule(store, inv_id, body)
    return lines[1:], unexplained  # a blank line between rules, none before the first


def raw(result: RunnerResult) -> str:
    """One runner group's own output, labeled the way it always was."""
    tag = "INCOMPLETE" if result.incomplete else "FAIL"
    return f"[{tag}] {', '.join(result.failed_ids or result.invariant_ids)} ({result.runner})\n{result.output}"


def count(report: VerifyReport) -> str:
    """ "1 rule fails" / "3 rules fail", or "" when the failure isn't a rule's (config, journal)."""
    n = len(report.failing_ids)
    return f"{n} rule{'' if n == 1 else 's'} fail{'s' if n == 1 else ''}" if n else ""
