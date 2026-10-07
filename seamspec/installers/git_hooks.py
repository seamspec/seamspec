"""git pre-commit installer (SPEC §16.4).

Writes `pre-commit` into the repo's hooks directory (respecting `core.hooksPath` and worktrees).
Never overwrites a hook it didn't write: with an existing hook, or a hook manager (pre-commit,
Husky, Lefthook), it prints the line to add instead.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

MARKER = "# Installed by seamspec init."
GATE = "seamspec verify --all --gate"


@dataclass
class HookResult:
    status: str  # created | updated | unchanged | manual | skipped | removed | absent
    path: str | None = None
    message: str = ""


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def render_hook(prefix: str) -> str:
    """The hook runs from the top of the worktree; `prefix` is where .seamspec/ lives inside it."""
    cd = f'cd "$(git rev-parse --show-toplevel)/{prefix}" || exit 1\n' if prefix else ""
    return (
        "#!/bin/sh\n"
        f"{MARKER} Remove this file to uninstall.\n"
        "# Runs every LOCKED SeamSpec invariant before each commit (SPEC §16.4).\n"
        "# GUI git clients often lack ~/.local/bin, where `uv tool` installs.\n"
        'PATH="${PATH:+$PATH:}$HOME/.local/bin"  # never an empty entry (= current folder)\n'
        f"{cd}"
        "# A branch where SeamSpec was never set up (no config here or in HEAD) has nothing to check.\n"
        "# A config that exists in HEAD but is missing here still runs the gate, and fails.\n"
        "# If git can't answer, fail closed: never guess that a branch is ungoverned.\n"
        "if [ ! -f .seamspec/config.toml ]; then\n"
        "  if ! command -v git >/dev/null 2>&1; then\n"
        '    echo "SeamSpec: git not found on PATH, so this branch can\'t be checked. Not committing." >&2\n'
        "    exit 1\n"
        "  fi\n"
        '  in_head=""\n'
        "  if git rev-parse --verify -q HEAD >/dev/null; then\n"
        "    in_head=$(git ls-tree --name-only HEAD -- ./.seamspec/config.toml) || {\n"
        '      echo "SeamSpec: git failed to read HEAD, so this branch can\'t be checked. Not committing." >&2\n'
        "      exit 1\n"
        "    }\n"
        "  fi\n"
        '  if [ -z "$in_head" ]; then\n'
        '    echo "SeamSpec: not set up on this branch; nothing to check." >&2\n'
        "    exit 0\n"
        "  fi\n"
        "fi\n"
        "if ! command -v seamspec >/dev/null 2>&1; then\n"
        '  echo "SeamSpec: the seamspec CLI is not installed (uv tool install seamspec)." >&2\n'
        '  echo "SeamSpec: install it, or delete this hook to stop checking." >&2\n'
        "  exit 1\n"
        "fi\n"
        f"exec {GATE}\n"
    )


def _manager(top: Path) -> str | None:
    if (top / ".pre-commit-config.yaml").is_file():
        return "pre-commit"
    if (top / ".husky").is_dir():
        return "Husky"
    if any((top / n).is_file() for n in ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")):
        return "Lefthook"
    return None


def install_pre_commit(root: Path) -> HookResult:
    top = _git(root, "rev-parse", "--show-toplevel")
    hooks = _git(root, "rev-parse", "--git-path", "hooks")
    prefix = _git(root, "rev-parse", "--show-prefix")
    if top is None or hooks is None or prefix is None:
        return HookResult("skipped", message="not a git repository; no pre-commit hook installed")
    manager = _manager(Path(top))
    if manager:
        return HookResult(
            "manual",
            message=f"{manager} manages your git hooks: add a pre-commit step that runs `{GATE}` "
            f"from {prefix.rstrip('/') or 'the repo root'}.",
        )
    hooks_dir = (root / hooks) if not os.path.isabs(hooks) else Path(hooks)
    path = hooks_dir / "pre-commit"
    text = render_hook(prefix.rstrip("/"))
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="replace")
        if MARKER not in old:
            return HookResult(
                "manual", str(path), f"{path} already exists and wasn't written by SeamSpec: add `{GATE}` to it."
            )
        if old == text:
            return HookResult("unchanged", str(path))
    status = "updated" if path.exists() else "created"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return HookResult(status, str(path))


def uninstall_pre_commit(root: Path) -> HookResult:
    """Remove the pre-commit hook only if SeamSpec wrote it: removed | absent | manual."""
    hooks = _git(root, "rev-parse", "--git-path", "hooks")
    if hooks is None:
        return HookResult("absent")
    path = ((root / hooks) if not os.path.isabs(hooks) else Path(hooks)) / "pre-commit"
    if not path.is_file():
        return HookResult("absent")
    if MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        return HookResult("manual", str(path), f"{path} wasn't written by SeamSpec; left as is.")
    path.unlink()
    return HookResult("removed", str(path))
