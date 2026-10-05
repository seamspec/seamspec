from __future__ import annotations

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
