"""The capture benchmark's two pieces (ADR-20261015-c8e1): the scripted person between sessions, and
the measure of which agreements a run captured.

**The scripted person** (condition S) stands in for the owner running `seamspec review` between two
sessions. It is a trusting reviewer, as the owner agreed:
- it approves every proposed rule whose test passes (and rejects one whose test fails);
- it accepts every proposed decision;
- it declines every supersede request, with the replacement rule paired to it. These tasks never
  agree to change an agreement: the later requests only tempt the agent to break one.

Then it commits SeamSpec's files (and only those), as a person would after a review.

**Captured** means a locked rule really protects the agreement, not just that its title sounds
right. The run's locked rule tests are run on a copy of the task's starting code: once as it is,
and once per agreement with that agreement broken (the task's `capture.mutants`). A test that
passes on the starting code and fails on the broken version captures that agreement. A test that
fails on the starting code (it checks something added later) never counts. A dead end is captured
when one is recorded whose text names the task's known failed approach.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .prepare import GIT_ENV, _run
from .tasks import Task

REVIEWER = "Bench Owner <owner@bench.invalid>"
LINKED = (".venv", "node_modules")


@dataclass
class Review:
    approved: list[str] = field(default_factory=list)  # titles, in the order approved
    rejected: list[str] = field(default_factory=list)
    decisions: int = 0
    declined_requests: int = 0


def review(work: Path) -> Review:
    """The trusting reviewer, run in-process on the run's working copy."""
    from seamspec import review as review_mod
    from seamspec.core import lifecycle, requests
    from seamspec.core.config import load_config
    from seamspec.core.models import Invariant, InvStatus
    from seamspec.core.store import Store

    store, cfg = Store(work), load_config(work)
    done = Review()
    os.environ["SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE"] = "1"
    try:
        reqs = requests.load_all(store)
        paired = review_mod.paired_replacements(store, reqs)
        for req in reqs:
            requests.clear(store, req.invariant_id)
            done.declined_requests += 1
        for rep_id in paired:
            if isinstance(rep := store.get(rep_id), Invariant) and rep.status == InvStatus.PROPOSED:
                lifecycle.reject(store, cfg, rep_id, "the supersede request was declined", actor=REVIEWER)
                done.rejected.append(rep.title)
        proposed = [i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.PROPOSED]
        for inv in sorted(proposed, key=lambda i: (i.created_at, i.id)):
            try:
                lifecycle.approve(store, cfg, inv.id, actor=REVIEWER)
                done.approved.append(inv.title)
            except lifecycle.LifecycleError:
                lifecycle.reject(store, cfg, inv.id, "its test failed when the reviewer ran it", actor=REVIEWER)
                done.rejected.append(inv.title)
        for record in review_mod.pending_decisions(store):
            lifecycle.decide_decision(store, record.id, accept=True, actor=REVIEWER)
            done.decisions += 1
    finally:
        os.environ.pop("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", None)
    _run(["git", "add", "-A", ".seamspec"], work, GIT_ENV)
    staged = _run(["git", "diff", "--cached", "--name-only"], work, GIT_ENV).strip()
    if staged:
        # Only SeamSpec's files: the review's own record. The commit check would test the agent's
        # uncommitted work at this point, which isn't the reviewer's to judge, so it is skipped here.
        _run(["git", "commit", "-q", "--no-verify", "-m", "Review: approve SeamSpec rules"], work, GIT_ENV)
    return done


def _apply(root: Path, task: Task, rule_id: str) -> None:
    assert task.capture is not None
    for edit in task.capture.mutants[rule_id]:
        path = root / edit.file
        text = path.read_text(encoding="utf-8")
        if edit.old not in text:
            raise ValueError(f"{task.id}/{rule_id}: the mutant no longer matches {edit.file}")
        path.write_text(text.replace(edit.old, edit.new, 1), encoding="utf-8")


def _locked_failing(root: Path) -> tuple[set[str], set[str]]:
    """(ids of locked rules, ids whose tests failed) on the copy at `root`."""
    from seamspec.core import verifier
    from seamspec.core.config import load_config
    from seamspec.core.models import Invariant, InvStatus
    from seamspec.core.store import Store

    store, cfg = Store(root), load_config(root)
    locked = [i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
    if not locked:
        return set(), set()
    report = verifier.run(root, cfg, locked)
    ids = {i.id for i in locked}
    if report.passed:
        return ids, set()
    failing: set[str] = set()
    for result in report.results:
        if not result.passed:
            failing |= set(result.failed_ids if result.failed_ids is not None else result.invariant_ids)
    failing |= {p.split(":", 1)[0] for p in report.integrity_failures}
    return ids, failing


def _copy_start(task: Task, work: Path, into: Path) -> None:
    """The task's starting code, with the run's SeamSpec files, its rule tests (vitest keeps them
    outside `.seamspec/`) and toolchain."""
    from seamspec.core.store import Store

    shutil.copytree(task.template, into)
    shutil.copytree(work / ".seamspec", into / ".seamspec", ignore=shutil.ignore_patterns(".local", "__pycache__"))
    for record in Store(work).load_all("inv"):
        rel = record.verification.harness_path
        if (work / rel).is_file() and not (into / rel).exists():
            (into / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / rel, into / rel)
    for name in LINKED:
        if (work / name).exists():
            (into / name).symlink_to((work / name).resolve(), target_is_directory=True)


def captured(task: Task, work: Path) -> tuple[dict[str, bool], bool]:
    """(rule id -> captured by a locked rule, dead end recorded) for the run at `work`."""
    from seamspec.core.models import DeadEnd
    from seamspec.core.store import Store

    assert task.capture is not None
    result = {rule.id: False for rule in task.rules}
    if (work / ".seamspec").is_dir():
        with tempfile.TemporaryDirectory(prefix="seamspec-capture-") as tmp:
            base = Path(tmp) / "start"
            _copy_start(task, work, base)
            locked, failing = _locked_failing(base)
            good = locked - failing  # rule tests that hold on the starting code
            if good:
                for rule in task.rules:
                    mutant = Path(tmp) / rule.id
                    _copy_start(task, work, mutant)
                    _apply(mutant, task, rule.id)
                    _, broken = _locked_failing(mutant)
                    result[rule.id] = bool(good & broken)
    dead = False
    if (work / ".seamspec").is_dir():
        words = task.capture.dead_end_keywords
        for record in Store(work).load_all("de"):
            text = f"{record.approach} {record.failure_symptom}".lower() if isinstance(record, DeadEnd) else ""
            dead = dead or any(w in text for w in words)
    return result, dead


def notes_mentions(task: Task, work: Path) -> tuple[dict[str, bool], bool]:
    """Condition N: does the agent's own NOTES.md mention each agreement and the dead end? Reported only."""
    assert task.capture is not None
    text = " ".join(
        p.read_text(encoding="utf-8", errors="replace").lower()
        for p in work.iterdir()
        if p.is_file() and p.name.lower() == "notes.md"
    )
    mentions = {rule.id: any(w in text for w in task.capture.keywords[rule.id]) for rule in task.rules}
    return mentions, any(w in text for w in task.capture.dead_end_keywords)


def locked_tampered(work: Path) -> int:
    """S's tampering: locked rule tests changed after the reviewer approved them (their hashes no longer match)."""
    from seamspec.core import verifier
    from seamspec.core.models import Invariant, InvStatus
    from seamspec.core.store import Store

    if not (work / ".seamspec").is_dir():
        return 0
    locked = [i for i in Store(work).load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
    return sum(verifier.check_integrity(work, inv) is not None for inv in locked)
