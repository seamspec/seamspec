"""Invariant and dead-end lifecycle (SPEC §11, §19.8).

Agents may propose invariants, log dead ends and request supersedes. Only a human at an
interactive terminal may approve, reject, supersede or retire. Every human status change is
journaled (§11.1).
"""

from __future__ import annotations

import contextlib
import getpass
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypedDict

from pydantic import ValidationError

from . import adr, journal, requests, verifier
from .config import Config
from .hashing import sha256_file, sha256_text
from .models import DeadEnd, Invariant, InvStatus, Origin, Scope, Verification, utcnow
from .redact import redact
from .store import Store, atomic_write

PROPOSED_DIR = Path(".seamspec") / "proposed"
RETIRED_DIR = Path(".seamspec") / "retired"
ORIGIN_MAX = 2000
SYMPTOM_MAX = 1000


class LifecycleError(RuntimeError):
    pass


class ApprovalError(LifecycleError):
    pass


class AdrDraft(TypedDict):
    context: str
    decision: str
    consequences: list[str]


# --- identity and interactivity ------------------------------------------------------------------


def require_interactive() -> None:
    """Human-only transitions need a terminal. A speed bump, not a security boundary (§19.8)."""
    if os.environ.get("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE") == "1":
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ApprovalError("This needs an interactive terminal. Run `seamspec review` yourself.")


def approver_identity(store: Store) -> str:
    """git `user.name <user.email>`, falling back to the OS user name (§11.1)."""

    def git(key: str) -> str:
        try:
            out = subprocess.run(["git", "config", key], cwd=store.root, capture_output=True, text=True, timeout=5)
            return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    name, email = git("user.name"), git("user.email")
    if name and email:
        return f"{name} <{email}>"
    return name or getpass.getuser()


# --- harness locations ---------------------------------------------------------------------------


def proposed_path(cfg: Config, runner: str, inv_id: str) -> str:
    """Proposed harnesses wait outside every test tree (§12A.5)."""
    filename = cfg.runners[runner].filename.format(id=inv_id)
    return str(PurePosixPath(PROPOSED_DIR.as_posix()) / inv_id / filename)


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    with contextlib.suppress(OSError):  # tidy empty per-id folders
        src.parent.rmdir()


@contextlib.contextmanager
def harness_in_place(store: Store, cfg: Config, inv: Invariant) -> Iterator[Invariant]:
    """Temporarily copy a PROPOSED harness to its runner's location, so the runner finds it
    exactly as it will once approved (used by `verify --proposed` and red-green)."""
    runner = cfg.runners.get(inv.verification.runner)
    if runner is None:
        raise LifecycleError(f"unknown runner {inv.verification.runner!r}")
    src = store.root / inv.verification.harness_path
    final_rel = runner.harness_path(inv.id)
    dst = store.root / final_rel
    if dst.exists():
        raise LifecycleError(f"{final_rel} already exists; remove it before verifying {inv.id}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    try:
        yield inv.model_copy(update={"verification": inv.verification.model_copy(update={"harness_path": final_rel})})
    finally:
        dst.unlink(missing_ok=True)


# --- agent-side operations -----------------------------------------------------------------------


def _origin(cfg: Config, origin_type: str, text: str, ref: str | None) -> Origin:
    text = redact(text) if cfg.braindump.redact_secrets else text
    return Origin(type=origin_type, text=text[:ORIGIN_MAX], ref=ref)  # type: ignore[arg-type]


def pending_count(store: Store) -> int:
    return sum(1 for i in store.load_all("inv") if i.status == InvStatus.PROPOSED)


def propose_invariant(
    store: Store,
    cfg: Config,
    *,
    title: str,
    assertion: str,
    scope_paths: list[str],
    runner: str,
    harness_code: str,
    origin_text: str,
    origin_type: Literal["prompt", "braindump", "manual"] = "prompt",
    origin_ref: str | None = None,
    scope_tags: list[str] | None = None,
    replace_id: str | None = None,
    adr_draft: AdrDraft | None = None,
    by_human: bool = False,
) -> dict[str, Any]:
    """Create (or, with `replace_id`, update) a PROPOSED invariant. Never runs anything (§12.4.3)."""
    if runner not in cfg.runners:
        raise LifecycleError(f"unknown runner {runner!r}; configured: {', '.join(sorted(cfg.runners)) or 'none'}")
    if not harness_code.strip():
        raise LifecycleError("harness_code is empty")

    existing: Invariant | None = None
    if replace_id is not None:
        found = store.get(replace_id)
        if not isinstance(found, Invariant) or found.status != InvStatus.PROPOSED:
            raise LifecycleError(f"{replace_id} is not a PROPOSED invariant; only proposals can be replaced")
        existing = found
    elif not by_human and pending_count(store) >= cfg.proposals.max_pending:
        return {
            "error": "queue_full",
            "pending": pending_count(store),
            "message": "Review queue is full. Ask the user to run `seamspec review`.",
        }

    inv_id = existing.id if existing else store.new_id("inv")
    harness_rel = proposed_path(cfg, runner, inv_id)
    try:
        inv = Invariant(
            id=inv_id,
            title=title,
            assertion=assertion,
            scope=Scope(paths=scope_paths, tags=scope_tags or []),
            status=InvStatus.PROPOSED,
            origin=_origin(cfg, origin_type, origin_text, origin_ref),
            verification=Verification(runner=runner, harness_path=harness_rel),
            adr_id=existing.adr_id if existing else None,
            created_at=existing.created_at if existing else utcnow(),
        )
    except ValidationError as exc:
        raise LifecycleError(f"invalid proposal: {exc}") from exc

    if existing and existing.verification.harness_path != harness_rel:
        (store.root / existing.verification.harness_path).unlink(missing_ok=True)
    atomic_write(store.root / harness_rel, harness_code if harness_code.endswith("\n") else harness_code + "\n")

    if adr_draft is not None and inv.adr_id is None:
        record = adr.create(
            store,
            title=title,
            context=adr_draft["context"],
            decision=adr_draft["decision"],
            consequences=list(adr_draft.get("consequences", [])),
            scopes=scope_paths,
            invariants=[(inv_id, assertion)],
        )
        inv.adr_id = record.id

    (store.save if existing else store.create)(inv)
    return {
        "id": inv_id,
        "status": "PROPOSED",
        "harness_path": harness_rel,
        "adr_id": inv.adr_id,
        "verify": {"status": "pending", "run": f"seamspec verify --proposed {inv_id}"},
    }


def log_dead_end(
    store: Store,
    cfg: Config,
    *,
    scope_paths: list[str],
    approach: str,
    failure_symptom: str,
    related_invariant: str | None = None,
    source: Literal["verifier", "braindump", "manual", "agent"] = "agent",
) -> dict[str, Any]:
    """Record a failed approach. No approval needed: dead ends never gate anything (§11.3)."""
    if related_invariant is not None:
        store.get(related_invariant)  # must exist
    symptom = redact(failure_symptom) if cfg.braindump.redact_secrets else failure_symptom
    try:
        de = DeadEnd(
            id=store.new_id("de"),
            scope=Scope(paths=scope_paths),
            approach=approach,
            failure_symptom=symptom[:SYMPTOM_MAX],
            source=source,
            related_invariant=related_invariant,
        )
    except ValidationError as exc:
        raise LifecycleError(f"invalid dead end: {exc}") from exc
    store.create(de)
    return {"id": de.id, "status": "ACTIVE"}


def request_supersede(
    store: Store, invariant_id: str, reason: str, replacement_id: str | None = None
) -> dict[str, Any]:
    """Ask the human to retire or replace a LOCKED invariant (§11.2). Changes no record."""
    inv = store.get(invariant_id)
    if not isinstance(inv, Invariant) or inv.status != InvStatus.LOCKED:
        raise LifecycleError(f"{invariant_id} is not LOCKED; only locked invariants can be superseded")
    if not reason.strip():
        raise LifecycleError("a reason is required")
    if replacement_id is not None:
        _check_replacement(store, invariant_id, replacement_id)
    requests.save(store, requests.new(invariant_id, reason.strip(), replacement_id))
    return {"request_id": invariant_id, "status": "pending", "next": "Ask the user to run `seamspec review`."}


def _check_replacement(store: Store, old_id: str, replacement_id: str) -> None:
    if replacement_id == old_id:
        raise LifecycleError("an invariant can't replace itself")
    rep = store.get(replacement_id)
    if not isinstance(rep, Invariant) or rep.status not in (InvStatus.PROPOSED, InvStatus.LOCKED):
        raise LifecycleError(f"replacement {replacement_id} must be PROPOSED or LOCKED")


# --- human-only operations -----------------------------------------------------------------------


def _get_inv(store: Store, inv_id: str) -> Invariant:
    inv = store.get(inv_id)
    if not isinstance(inv, Invariant):
        raise LifecycleError(f"{inv_id} is not an invariant")
    return inv


def _retire_harness(store: Store, inv: Invariant) -> str:
    """Move a harness out of every test tree to .seamspec/retired/<id>/ (§12A.5)."""
    src = store.root / inv.verification.harness_path
    dst_rel = str(PurePosixPath(RETIRED_DIR.as_posix()) / inv.id / PurePosixPath(inv.verification.harness_path).name)
    if src.is_file():
        _move(src, store.root / dst_rel)
        return dst_rel
    return inv.verification.harness_path


@dataclass
class ApprovalResult:
    invariant: Invariant
    report: verifier.VerifyReport


def approve(
    store: Store,
    cfg: Config,
    inv_id: str,
    actor: str | None = None,
    confirm_config: dict[str, str] | None = None,
) -> ApprovalResult:
    """PROPOSED → LOCKED. The caller has shown the human the full harness (§12.4.3 rule 4).

    Approval writes the runner config fingerprints. If the runner config changed since it was last
    confirmed, the caller must pass `confirm_config`: the fingerprints of exactly the bytes it showed
    the human (`review.show_config_changes`). If the files changed again after that, approval is
    refused, so an unseen version can never be confirmed."""
    require_interactive()
    inv = _get_inv(store, inv_id)
    if inv.status != InvStatus.PROPOSED:
        raise ApprovalError(f"{inv_id} is {inv.status.value}, not PROPOSED")
    runner = cfg.runners.get(inv.verification.runner)
    if runner is None:
        raise ApprovalError(f"{inv_id} uses unknown runner {inv.verification.runner!r}")

    changed = verifier.check_fingerprints(store.root, cfg)
    prints = verifier.current_fingerprints(store.root, cfg)
    if changed:
        if confirm_config is None:
            raise ApprovalError(
                "runner config changed since it was last confirmed:\n  "
                + "\n  ".join(changed)
                + "\nReview it first (`seamspec review`), or confirm it when approving."
            )
        if prints != confirm_config:
            raise ApprovalError("runner config changed again after it was shown to you; review it again.")
    proposed = store.root / inv.verification.harness_path
    final_rel = runner.harness_path(inv.id)
    final = store.root / final_rel
    if not proposed.is_file():
        raise ApprovalError(f"{inv_id}: harness {inv.verification.harness_path} is missing")
    if final.exists():
        raise ApprovalError(f"{final_rel} already exists; remove it before approving {inv_id}")
    _move(proposed, final)
    staged = inv.model_copy(update={"verification": inv.verification.model_copy(update={"harness_path": final_rel})})

    report = verifier.run(store.root, cfg, [staged], fingerprints=prints)
    if not report.passed:
        _move(final, proposed)  # put it back; nothing was written
        raise ApprovalError(f"{inv_id}: its test is not passing, so it can't be approved.\n{_report_text(report)}")

    verifier.confirm_fingerprints(store.root, prints)
    who = actor or approver_identity(store)
    locked = staged.model_copy(
        update={
            "status": InvStatus.LOCKED,
            "approved_at": utcnow(),
            "approved_by": who,
            "verification": staged.verification.model_copy(
                update={"harness_sha256": sha256_file(final), "assertion_sha256": sha256_text(inv.assertion)}
            ),
        }
    )
    locked = Invariant.model_validate(locked.model_dump())
    store.save(locked)
    journal.append(store, inv.id, "PROPOSED", "LOCKED", who)
    if locked.adr_id:
        with contextlib.suppress(KeyError):
            adr.set_status(store, locked.adr_id, "ACCEPTED")
    return ApprovalResult(locked, report)


def reject(
    store: Store, cfg: Config, inv_id: str, reason: str, as_dead_end: bool = False, actor: str | None = None
) -> dict[str, Any]:
    """PROPOSED → REJECTED, optionally recording the approach as a dead end (§11.1)."""
    require_interactive()
    if not reason.strip():
        raise LifecycleError("a reason is required")
    inv = _get_inv(store, inv_id)
    if inv.status != InvStatus.PROPOSED:
        raise LifecycleError(f"{inv_id} is {inv.status.value}, not PROPOSED")
    who = actor or approver_identity(store)
    harness = _retire_harness(store, inv)
    rejected = inv.model_copy(
        update={
            "status": InvStatus.REJECTED,
            "status_reason": reason.strip(),
            "verification": inv.verification.model_copy(update={"harness_path": harness}),
        }
    )
    store.save(Invariant.model_validate(rejected.model_dump()))
    journal.append(store, inv.id, "PROPOSED", "REJECTED", who)
    if inv.adr_id:
        with contextlib.suppress(KeyError):
            adr.set_status(store, inv.adr_id, "REJECTED")
    out: dict[str, Any] = {"id": inv_id, "status": "REJECTED"}
    if as_dead_end:
        out["dead_end"] = log_dead_end(
            store,
            cfg,
            scope_paths=inv.scope.paths,
            approach=inv.assertion,
            failure_symptom=reason.strip(),
            related_invariant=inv.id,
            source="manual",
        )["id"]
    return out


def supersede(
    store: Store,
    cfg: Config,
    inv_id: str,
    reason: str | None = None,
    replacement_id: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """LOCKED → SUPERSEDED, by explicit command or by approving a pending request (§11.2).
    The replacement, if any, still needs its own approval."""
    require_interactive()
    inv = _get_inv(store, inv_id)
    if inv.status != InvStatus.LOCKED:
        raise LifecycleError(f"{inv_id} is {inv.status.value}, not LOCKED")
    pending = requests.get(store, inv_id)
    reason = (reason or (pending.reason if pending else "")).strip()
    replacement_id = replacement_id or (pending.replacement_id if pending else None)
    if not reason:
        raise LifecycleError("a reason is required (or a pending supersede request)")
    if replacement_id is not None:
        _check_replacement(store, inv_id, replacement_id)

    who = actor or approver_identity(store)
    harness = _retire_harness(store, inv)
    retired = inv.model_copy(
        update={
            "status": InvStatus.SUPERSEDED,
            "status_reason": reason,
            "superseded_by": replacement_id,
            "verification": inv.verification.model_copy(update={"harness_path": harness}),
        }
    )
    store.save(Invariant.model_validate(retired.model_dump()))
    journal.append(store, inv.id, "LOCKED", "SUPERSEDED", who)
    requests.clear(store, inv_id)
    if inv.adr_id:
        with contextlib.suppress(KeyError):
            adr.set_status(store, inv.adr_id, "SUPERSEDED")
    return {"id": inv_id, "status": "SUPERSEDED", "superseded_by": replacement_id}


def retire_dead_end(store: Store, de_id: str, reason: str) -> dict[str, Any]:
    """ACTIVE → RETIRED, e.g. once a library upgrade makes the approach valid again (§11.3)."""
    require_interactive()
    if not reason.strip():
        raise LifecycleError("a reason is required")
    de = store.get(de_id)
    if not isinstance(de, DeadEnd):
        raise LifecycleError(f"{de_id} is not a dead end")
    if de.status != "ACTIVE":
        raise LifecycleError(f"{de_id} is already {de.status}")
    store.save(DeadEnd.model_validate({**de.model_dump(), "status": "RETIRED", "retired_reason": reason.strip()}))
    return {"id": de_id, "status": "RETIRED"}


def _report_text(report: verifier.VerifyReport) -> str:
    parts = report.integrity_failures + report.config_failures
    parts += [r.output for r in report.results if not r.passed]
    return "\n".join(parts)[-3000:]
