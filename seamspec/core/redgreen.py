"""Red-green check: does a proposed test fail *without* the change? (SPEC §11.4)

Information for the human reviewer, never a gate. A test that already passes on `HEAD` either
protects behavior that existed before (fine for characterization tests) or checks nothing (a
strong hint on a brand-new feature).

How: run the proposed test on the working tree, then in a temporary detached `git worktree` of
`HEAD`. The worktree gets SeamSpec's *current* settings (config.toml and each runner's config
files, so both runs use the same runner) and links to the project's `.venv` / `node_modules`,
which a fresh worktree doesn't have. The worktree is always removed afterwards.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import verifier
from .config import Config
from .lifecycle import LifecycleError, harness_in_place
from .models import Invariant
from .root import CONFIG_REL
from .store import Store

Verdict = Literal["yes", "no", "n/a"]
LINKED = (".venv", "venv", "node_modules")


@dataclass
class RedGreen:
    verdict: Verdict  # "yes" = fails without the change (good), "no" = passes on HEAD too
    detail: str  # one line for the reviewer

    def line(self) -> str:
        return f"fails without your change: {self.verdict} ({self.detail})"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ran_tests(report: verifier.VerifyReport) -> bool:
    """False when the run couldn't really happen (deadline, missing runner, config mismatch)."""
    if report.config_failures or report.integrity_failures or report.incomplete:
        return False
    return not any("not found" in r.output and not r.passed for r in report.results)


def check(store: Store, cfg: Config, inv: Invariant) -> RedGreen:
    root = store.root
    prints = verifier.current_fingerprints(root, cfg)

    # 1. Working tree: the proposal should pass here.
    try:
        with harness_in_place(store, cfg, inv) as staged:
            now = verifier.run(root, cfg, [staged], fingerprints=prints)
    except (LifecycleError, OSError) as exc:
        return RedGreen("n/a", f"couldn't run it here: {exc}")
    if not _ran_tests(now):
        return RedGreen("n/a", "the test couldn't run on your working tree")
    if not now.passed:
        return RedGreen("n/a", "it fails on your working tree too, so approval would be refused")

    # 2. HEAD, in a throwaway worktree.
    prefix = _git(root, "rev-parse", "--show-prefix")
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if prefix is None or prefix.returncode != 0:
        return RedGreen("n/a", "not a git repository, so there's no HEAD to compare with")
    if head is None or head.returncode != 0:
        return RedGreen("n/a", "no commits yet, so there's no HEAD to compare with")

    tmp = Path(tempfile.mkdtemp(prefix="seamspec-redgreen-"))
    wt = tmp / "head"
    added = _git(root, "worktree", "add", "--detach", "-q", str(wt), "HEAD")
    try:
        if added is None or added.returncode != 0:
            return RedGreen("n/a", "couldn't create a temporary worktree of HEAD")
        wt_root = wt / prefix.stdout.strip()
        wt_root.mkdir(parents=True, exist_ok=True)
        _prepare(root, wt_root, cfg, inv)
        runner = cfg.runners[inv.verification.runner]
        staged_head = inv.model_copy(
            update={"verification": inv.verification.model_copy(update={"harness_path": runner.harness_path(inv.id)})}
        )
        before = verifier.run(wt_root, cfg, [staged_head], fingerprints=prints)
    finally:
        _git(root, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(tmp, ignore_errors=True)
        _git(root, "worktree", "prune")

    if not _ran_tests(before):
        return RedGreen("n/a", "the test couldn't run against HEAD")
    if before.passed:
        return RedGreen("no", "it passes on HEAD too: fine if it protects behavior that already existed")
    return RedGreen("yes", "it fails on HEAD and passes with your change")


def _prepare(root: Path, wt_root: Path, cfg: Config, inv: Invariant) -> None:
    """Give the HEAD worktree today's SeamSpec settings, the proposed test and the project's envs."""
    files = [CONFIG_REL.as_posix(), *(rel for r in cfg.runners.values() for rel in r.config_files)]
    for rel in files:
        src = root / rel
        if src.is_file():
            dst = wt_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    runner = cfg.runners[inv.verification.runner]
    dst = wt_root / runner.harness_path(inv.id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / inv.verification.harness_path, dst)
    for name in LINKED:
        src = root / name
        if src.exists() and not (wt_root / name).exists():
            (wt_root / name).symlink_to(src.resolve(), target_is_directory=True)
