"""Scope matching with gitignore-style globs (SPEC §19.5)."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import pathspec

if TYPE_CHECKING:
    from .config import Config


@lru_cache(maxsize=512)
def _spec(patterns: tuple[str, ...]) -> pathspec.GitIgnoreSpec:
    return pathspec.GitIgnoreSpec.from_lines(patterns)


def matches(patterns: list[str], rel_path: str) -> bool:
    """True if repo-relative POSIX `rel_path` matches any pattern (gitignore semantics, incl. `!`)."""
    return _spec(tuple(patterns)).match_file(rel_path)


def effective_protected_paths(cfg: Config) -> list[str]:
    """One list used by the PreToolUse hook, CODEOWNERS and `doctor --ci` (§12A.5):
    protect.paths + every runner's harness glob + every runner's config files."""
    globs = list(cfg.protect.paths)
    for runner in cfg.runners.values():
        globs.append(runner.protect_glob())
        globs.extend(runner.config_files)
    return globs
