"""Project root discovery and repo-relative paths (SPEC §19.1)."""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_REL = Path(".seamspec") / "config.toml"


class RootNotFound(RuntimeError):
    pass


def find_root(start: Path | None = None) -> Path:
    """Resolve the project root: $SEAMSPEC_ROOT, else walk up to .seamspec/config.toml."""
    env = os.environ.get("SEAMSPEC_ROOT")
    if env:
        root = Path(env).resolve()
        if not (root / CONFIG_REL).is_file():
            raise RootNotFound(f"SEAMSPEC_ROOT={env} has no {CONFIG_REL}. Run `seamspec init` there.")
        return root
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_REL).is_file():
            return candidate
    raise RootNotFound(
        f"No {CONFIG_REL.as_posix()} found in {current} or any folder above it. "
        "Run SeamSpec from inside your repository, or run `seamspec init` there."
    )


def to_rel(root: Path, path: str | Path) -> str | None:
    """Repo-relative POSIX path, or None if outside the repo."""
    p = Path(path)
    p = (p if p.is_absolute() else root / p).resolve()
    try:
        return p.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
