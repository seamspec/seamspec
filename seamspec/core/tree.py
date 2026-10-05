"""Git working-tree helpers (SPEC §12.2 scoped mode)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def changed_files(root: Path) -> list[str] | None:
    """Files changed vs HEAD (staged or not) plus untracked, non-ignored files, relative to `root`.
    None when this isn't a git repo (callers then fall back to running everything)."""
    prefix = _git(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    has_head = _git(root, "rev-parse", "--verify", "-q", "HEAD") is not None
    tracked = _git(root, "diff", "--name-only", "--relative", "HEAD") if has_head else ""
    staged = _git(root, "diff", "--name-only", "--relative", "--cached") or ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    if tracked is None or untracked is None:
        return None
    names = {n for n in (tracked + "\n" + staged + "\n" + untracked).splitlines() if n}
    return sorted(names)
