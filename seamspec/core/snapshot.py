"""The commit check tests what the commit records (SPEC §16.4, ADR-20261014-3b1e).

`git commit` records the index (what `git add` staged), not the files on disk. Run against the
working tree, the gate passed a commit whose staged code was broken, because the file on disk had
been fixed after `git add` (found testing on Antigravity). So when the index and the working tree
differ, the gate copies the index into a temporary folder (`git checkout-index`) and runs the locked
tests there.

- **Code** comes from the index: it is what the commit records.
- **SeamSpec's ledger** (rules, their tests, config) comes from disk, the ledger the CLI keeps and a
  human approved, the same one the Stop hook and `seamspec verify` use. So do rule tests kept outside
  `.seamspec/` (vitest's `tests/seamspec/`). Tracked files of either whose staged copy differs from
  disk are refused before anything runs, so a commit can't record a ledger the gate didn't check.
  Untracked ones (a rule approved but not staged yet) still apply.
- **Environments**: the copy links the project's `.venv` / `venv` / `node_modules`, and a Python
  runner starts through red-green's start-script copy (§11.4), which points imports inside the
  repository at the copy, so an editable install can't hand the run the working tree's code. With an
  editable install, every runner that runs needs its own proof that its redirect ran, unless it is
  known not to start Python (Node). Where that can't be had, the gate can't tell what the commit
  contains: it fails closed and says how to commit anyway. A commit that runs no rules needs none
  (ADR-20261026-5b8e).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .redgreen import LINKED, applied_marker, editable_install, shim_runner, starts_without_python

LEDGER = ".seamspec"
LOCAL = ".local"


class SnapshotError(Exception):
    """The staged files couldn't be checked; the message says what to do."""


@dataclass
class Snapshot:
    root: Path  # the SeamSpec root inside the copy
    shims: Path
    redirected: bool  # a start-script copy is first on the runners' PATH
    must_redirect: bool  # an editable install: a runner's run only counts if its redirect ran
    first_on_path: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)  # runner -> the file its redirect writes
    no_python: set[str] = field(default_factory=set)  # runners known not to start Python

    def unredirected(self, runners: Collection[str]) -> list[str]:
        """Of `runners`, the ones that may import Python code and have no redirect."""
        return sorted(n for n in runners if n not in self.evidence and n not in self.no_python)

    def trustworthy(self, ran: Collection[str]) -> bool:
        """False when a runner in `ran` may have imported the working tree's code instead of the
        commit's. Each one needs its own proof: one redirected runner says nothing about another."""
        if not self.must_redirect:
            return True
        return not self.unredirected(ran) and all(
            (self.shims / self.evidence[n]).exists() for n in ran if n in self.evidence
        )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _top_and_prefix(root: Path) -> tuple[Path, str] | None:
    top = _git(root, "rev-parse", "--show-toplevel")
    prefix = _git(root, "rev-parse", "--show-prefix")
    if top is None or top.returncode != 0 or prefix is None or prefix.returncode != 0:
        return None
    return Path(top.stdout.strip()), prefix.stdout.strip()


def differs(root: Path) -> bool:
    """Does the commit record something other than what's on disk? True for unstaged changes to
    tracked files or for untracked, non-ignored files anywhere in the repository. False outside git."""
    found = _top_and_prefix(root)
    if found is None:
        return False
    top, _ = found
    diff = _git(top, "diff", "--quiet")
    if diff is None or diff.returncode not in (0, 1):
        return True  # can't tell: check the staged copy rather than guess
    if diff.returncode == 1:
        return True
    untracked = _git(top, "ls-files", "--others", "--exclude-standard")
    return untracked is None or untracked.returncode != 0 or bool(untracked.stdout.strip())


def _harness_dirs(cfg: Config) -> list[str]:
    """Folders of rule tests outside `.seamspec/` (vitest's `tests/seamspec`): part of the ledger here."""
    dirs = {r.harness_dir.rstrip("/") for r in cfg.runners.values()}
    return sorted(d for d in dirs if d != LEDGER and not d.startswith(f"{LEDGER}/"))


def ledger_differs(root: Path, cfg: Config | None = None) -> bool:
    """Tracked SeamSpec files, and rule tests kept outside `.seamspec/`, whose staged copy differs
    from the one on disk."""
    found = _top_and_prefix(root)
    if found is None:
        return False
    top, prefix = found
    paths = [LEDGER, *(_harness_dirs(cfg) if cfg is not None else [])]
    diff = _git(top, "diff", "--quiet", "--", *(f"{prefix}{p}" for p in paths))
    return diff is None or diff.returncode != 0


@contextmanager
def staged(root: Path, cfg: Config, runners: Collection[str]) -> Iterator[Snapshot]:
    """A temporary copy of what the commit records, with today's ledger, removed afterwards.
    `runners`: the ones the commit's rules use, checked before anything runs."""
    found = _top_and_prefix(root)
    if found is None:
        raise SnapshotError("SeamSpec couldn't ask git what this commit contains.")
    if ledger_differs(root, cfg):
        stage = " ".join(f"`git add {p}`" for p in [LEDGER, *_harness_dirs(cfg)])
        raise SnapshotError(
            "SeamSpec's files staged for this commit differ from the ones on disk, so the commit would record "
            f"rules the check didn't run. Stage them again ({stage}) and commit."
        )
    tmp = Path(tempfile.mkdtemp(prefix="seamspec-commit-"))
    try:
        try:
            snap = _prepare(root, cfg, *found, tmp)
        except OSError as exc:  # e.g. symlinks not allowed (Windows), permissions
            raise SnapshotError(f"SeamSpec couldn't prepare a copy of the staged files: {exc}") from None
        if snap.must_redirect and snap.unredirected(runners):
            raise SnapshotError(EDITABLE)
        yield snap
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prepare(root: Path, cfg: Config, top: Path, prefix: str, tmp: Path) -> Snapshot:
    copy = tmp / "commit"
    out = _git(top, "checkout-index", "--all", "--force", f"--prefix={copy}/")
    if out is None or out.returncode != 0:
        raise SnapshotError("SeamSpec couldn't copy the staged files to check them.")
    snap_root = copy / prefix
    snap_root.mkdir(parents=True, exist_ok=True)
    ledger = root / LEDGER
    shutil.copytree(
        ledger,
        snap_root / LEDGER,
        dirs_exist_ok=True,
        ignore=lambda folder, names: [n for n in names if n == "__pycache__" or (n == LOCAL and folder == str(ledger))],
    )
    for rel in _harness_dirs(cfg):  # rule tests approved but not staged yet apply here too
        if (root / rel).is_dir():
            shutil.copytree(
                root / rel, snap_root / rel, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
            )
    for name in LINKED:
        src = root / name
        if src.exists() and not (snap_root / name).exists():
            (snap_root / name).symlink_to(src.resolve(), target_is_directory=True)
    shims = tmp / "bin"
    evidence: dict[str, str] = {}
    no_python: set[str] = set()
    for name in cfg.runners:
        if script := shim_runner(cfg, name, snap_root, shims, top, copy):
            evidence[name] = applied_marker(script)
        elif starts_without_python(cfg, name, snap_root):
            no_python.add(name)
    must_redirect = editable_install(root, top, os.environ)
    redirected = bool(evidence)
    return Snapshot(
        snap_root, shims, redirected, must_redirect, [str(shims)] if redirected else [], evidence, no_python
    )


EDITABLE = (
    "Files on disk differ from what this commit records, and this project is installed in editable mode, "
    "so SeamSpec can't run the tests against the staged code alone. Stage your changes (`git add`) or set "
    "them aside (`git stash --keep-index --include-untracked`), then commit."
)
