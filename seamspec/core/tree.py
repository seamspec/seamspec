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


def tree_fingerprint(root: Path) -> str | None:
    """Identity of the working tree as git sees it: HEAD plus the content of every changed or
    untracked, non-ignored file under `root`. Caches and reports that tests write (ignored files)
    don't change it. None outside git: callers then never skip a run."""
    import hashlib

    head = _git(root, "rev-parse", "-q", "--verify", "HEAD")
    files = changed_files(root)
    if files is None:
        return None
    h = hashlib.sha256((head or "no-head").strip().encode())
    for rel in files:
        h.update(b"\0" + rel.encode())
        p = root / rel
        if not p.is_file():
            h.update(b"<deleted>")
            continue
        try:
            with p.open("rb") as f:  # chunked: a large untracked file must not exhaust memory
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()
