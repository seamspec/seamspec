"""The second-actor benchmark (ADR-20261019-5f3b): a teammate changes the code, not the author.

After session 1 the author's work is pushed to a local bare repository ("origin"). A teammate
clones it: a clone carries only committed files, not `.git/hooks`, `.seamspec/.local` or the
author's local plugin install. Their agent gets only the tempting requests, then they push.

"CI" runs on a fresh clone of what was pushed, as a hosted CI would: the project's own tests for
every setup, plus `seamspec verify --all --ci` when the repository carries SeamSpec's config. A
push whose CI fails is blocked, as branch protection would block its merge. Nothing here talks to
GitHub.

The human edit is the demonstration (decided by construction, never counted as measured): a
scripted teammate pushes each agreement's violating patch on top of session 1's result.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .prepare import GIT_ENV, _run, _toolchain, git
from .tasks import Task

CI_TIMEOUT = 600


def push_origin(work: Path, origin: Path) -> None:
    """Commit what session 1 left (the author's push) and make the bare repository teammates clone."""
    git(work, "add", "-A")
    if git(work, "status", "--porcelain").strip():
        git(work, "commit", "-q", "--no-verify", "-m", "Author: end of session 1")  # bookkeeping, not the agent's
    if origin.exists():
        shutil.rmtree(origin)
    _run(["git", "clone", "-q", "--bare", str(work), str(origin)], work.parent, GIT_ENV)


def clone(task: Task, origin: Path, dest: Path) -> Path:
    """A teammate's (or CI's) fresh clone, with the project's toolchain and nothing else of the author's."""
    if dest.exists():
        shutil.rmtree(dest)
    _run(["git", "clone", "-q", str(origin), str(dest)], origin.parent, GIT_ENV)
    _toolchain(task, dest)
    return dest


def push(repo: Path) -> None:
    """The teammate pushes what they committed; uncommitted work stays on their machine."""
    git(repo, "push", "-q", "origin", "HEAD:main")


def _passes(cmd: list[str], cwd: Path) -> bool:
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env["PATH"] = os.pathsep.join([str(cwd / ".venv/bin"), str(cwd / "node_modules/.bin"), env.get("PATH", "")])
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=CI_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ci(task: Task, origin: Path, dest: Path) -> bool:
    """Does CI pass on what origin holds now?"""
    repo = clone(task, origin, dest)
    if task.language == "python":
        ok = _passes([str(repo / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo)
    else:
        ok = _passes(["npx", "vitest", "run"], repo)
    if (repo / ".seamspec/config.toml").is_file():  # SeamSpec's CI workflow, as it runs it
        ok = _passes(["seamspec", "verify", "--all", "--ci"], repo) and ok
    shutil.rmtree(repo, ignore_errors=True)
    return ok


def human_edits(task: Task, origin: Path, scratch: Path) -> dict[str, bool | None]:
    """The demonstration: rule id -> did the scripted hand edit land (pushed, CI passed)? None when the
    violating patch no longer matches the code session 1 left."""
    from .capture import _apply

    landed: dict[str, bool | None] = {}
    scratch.mkdir(parents=True, exist_ok=True)
    for rule in task.rules:
        bare = scratch / f"origin-{rule.id}.git"
        if bare.exists():
            shutil.rmtree(bare)
        _run(["git", "clone", "-q", "--bare", str(origin), str(bare)], scratch, GIT_ENV)
        mate = scratch / f"edit-{rule.id}"
        if mate.exists():
            shutil.rmtree(mate)
        _run(["git", "clone", "-q", str(bare), str(mate)], scratch, GIT_ENV)
        try:
            _apply(mate, task, rule.id)
        except ValueError:
            landed[rule.id] = None
            continue
        git(mate, "commit", "-q", "-am", f"Teammate: {rule.id}")
        push(mate)
        landed[rule.id] = ci(task, bare, scratch / f"ci-{rule.id}")
        shutil.rmtree(mate, ignore_errors=True)
        shutil.rmtree(bare, ignore_errors=True)
    return landed


def asked(log_dir: Path) -> bool:
    """Did the teammate's agent stop to ask (a supersede request, or a final message with a question)?
    Reported only."""
    for path in sorted(log_dir.glob("s2p*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                for part in event.get("message", {}).get("content", []) or []:
                    if isinstance(part, dict) and "request_supersede" in str(part.get("name", "")):
                        return True
            if event.get("type") == "result" and "?" in str(event.get("result") or ""):
                return True
    return False
