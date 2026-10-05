"""Helpers for verifier tests: real repos with real harnesses and LOCKED records."""

from __future__ import annotations

from pathlib import Path

from seamspec.core.config import Config, load_config
from seamspec.core.hashing import sha256_file, sha256_text
from seamspec.core.models import Invariant, InvStatus, Origin, Scope, Verification
from seamspec.core.store import Store

from .conftest import FIXED


def write_locked(
    root: Path, cfg: Config, inv_id: str, code: str, runner: str = "pytest", status: InvStatus = InvStatus.LOCKED
) -> Invariant:
    """Write a harness at the runner's path and a matching record (hashes taken now)."""
    rel = cfg.runners[runner].harness_path(inv_id)
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    assertion = f"Behaviour protected by {inv_id} holds."
    fields: dict = dict(
        id=inv_id,
        title=f"Rule {inv_id}",
        assertion=assertion,
        scope=Scope(paths=["src/**"]),
        status=status,
        origin=Origin(type="manual", text="test"),
        verification=Verification(runner=runner, harness_path=rel),
        created_at=FIXED,
    )
    if status == InvStatus.LOCKED:
        fields.update(approved_at=FIXED, approved_by="Test <t@example.com>")
        fields["verification"] = Verification(
            runner=runner, harness_path=rel, harness_sha256=sha256_file(path), assertion_sha256=sha256_text(assertion)
        )
    inv = Invariant(**fields)
    Store(root).save(inv)
    return inv


def reload(root: Path) -> Config:
    return load_config(root)
