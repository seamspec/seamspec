from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seamspec.core.hashing import sha256_text
from seamspec.core.models import DeadEnd, Invariant, InvStatus, Origin, Scope, Verification
from seamspec.core.store import Store
from seamspec.installers import scaffold

FIXED = datetime(2026, 10, 3, 8, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEAMSPEC_ROOT", raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A Python repo with SeamSpec initialised."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path)
    return tmp_path


@pytest.fixture
def py_repo(tmp_path: Path) -> Path:
    """A Python project with real code under src/ and SeamSpec initialised (no git)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/__init__.py").write_text("")
    (tmp_path / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    scaffold.init(tmp_path)
    return tmp_path


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Maya Rao", "GIT_AUTHOR_EMAIL": "maya@example.com",
           "GIT_COMMITTER_NAME": "Maya Rao", "GIT_COMMITTER_EMAIL": "maya@example.com"}  # fmt: skip
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def git_repo(py_repo: Path) -> Path:
    """py_repo as a git repository with everything committed, and a git identity set."""
    git(py_repo, "init", "-q", "-b", "main")
    git(py_repo, "config", "user.name", "Maya Rao")
    git(py_repo, "config", "user.email", "maya@example.com")
    git(py_repo, "add", "-A")
    git(py_repo, "commit", "-q", "-m", "init")
    return py_repo


@pytest.fixture
def store(repo: Path) -> Store:
    return Store(repo)


def make_invariant(
    inv_id: str = "inv_1a2b3c4d", status: InvStatus = InvStatus.PROPOSED, paths: list[str] | None = None, **extra
) -> Invariant:
    fields = dict(
        id=inv_id,
        title="Redis retry delay is capped",
        assertion="Exponential backoff for Redis queue retries never exceeds 30 seconds.",
        scope=Scope(paths=paths or ["src/queue/**"], tags=["resilience"]),
        status=status,
        origin=Origin(type="prompt", text="Add backoff, never more than 30s."),
        verification=Verification(runner="pytest", harness_path=f".seamspec/tests/test_{inv_id}.py"),
        created_at=FIXED,
    )
    if status == InvStatus.LOCKED:
        fields["approved_at"] = FIXED
        fields["approved_by"] = "Maya Rao <maya@example.com>"
        fields["verification"] = Verification(
            runner="pytest",
            harness_path=f".seamspec/tests/test_{inv_id}.py",
            harness_sha256="a" * 64,
            assertion_sha256=sha256_text(fields["assertion"]),
        )
    if status in (InvStatus.SUPERSEDED, InvStatus.REJECTED):
        fields["status_reason"] = "Requirement changed"
    fields.update(extra)
    return Invariant(**fields)


def make_dead_end(de_id: str = "de_9f8e7d6c", paths: list[str] | None = None, **extra) -> DeadEnd:
    fields = dict(
        id=de_id,
        scope=Scope(paths=paths or ["src/queue/**"]),
        approach="a global retry counter shared across workers",
        failure_symptom="caused a thundering herd on recovery",
        source="agent",
        created_at=FIXED,
    )
    fields.update(extra)
    return DeadEnd(**fields)
