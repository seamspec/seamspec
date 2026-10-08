"""`seamspec review`: one interactive pass over everything waiting for a human (SPEC §15, §11).

Order: runner config changes (they gate approvals) → dead ends recorded since the last review
(so wrong ones get retired early, §11.3) → supersede requests → proposed invariants, oldest first,
each with its full test and an optional red-green check (§11.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import typer

from .core import lifecycle, redgreen, requests, verifier
from .core.config import Config
from .core.hashing import sha256_bytes
from .core.models import DeadEnd, Invariant, InvStatus, utcnow
from .core.store import Store, atomic_write

STATE = "review.json"


@dataclass
class Tally:
    approved: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class Quit(Exception):
    pass


def _choice(label: str, keys: str, default: str) -> str:
    """One-letter answer from `keys`; re-asks on anything else. `q` stops the review."""
    while True:
        answer = str(typer.prompt(label, default=default, show_default=True)).strip().lower()[:1]
        if answer in keys:
            if answer == "q":
                raise Quit
            return answer
        typer.echo(f"  please answer one of: {', '.join(keys)}")


def show_invariant(store: Store, inv: Invariant) -> None:
    typer.echo(f"{inv.id} [{inv.status.value}] {inv.title}")
    typer.echo(f"  rule:   {inv.assertion}")
    typer.echo(f"  scope:  {', '.join(inv.scope.paths)}")
    typer.echo(f"  origin: {inv.origin.type}: {inv.origin.text[:300]}")
    typer.echo(f"  test:   {inv.verification.harness_path} (runner: {inv.verification.runner})")
    harness = store.root / inv.verification.harness_path
    if harness.is_file():
        typer.echo("  " + "-" * 60)
        for line in harness.read_text(encoding="utf-8").splitlines():
            typer.echo(f"  | {line}")
        typer.echo("  " + "-" * 60)


def show_config_changes(store: Store, cfg: Config) -> dict[str, str]:
    """Print changed runner config files in full. Returns the fingerprints of exactly the bytes
    that were read for display, so a confirmation can be bound to what the human saw."""
    confirmed = verifier.read_fingerprints(store.root)
    shown: dict[str, str] = {}
    for runner in cfg.runners.values():
        for rel in runner.config_files:
            path = store.root / rel
            if not path.is_file():
                typer.echo(f"  {rel}: runner config file is missing")
                continue
            data = path.read_bytes()
            shown[rel] = sha256_bytes(data)
            if shown[rel] != confirmed.get(rel):
                typer.echo(f"  {rel}: changed since it was last confirmed")
                for line in data.decode("utf-8", errors="replace").splitlines():
                    typer.echo(f"    | {line}")
    return shown


def _state(store: Store) -> dict:
    try:
        data = json.loads((store.local / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _last_review(store: Store) -> datetime | None:
    try:
        return datetime.fromisoformat(_state(store)["last_review_at"])
    except (ValueError, KeyError, TypeError):
        return None


def _seen_dead_ends(store: Store) -> set[str]:
    """Dead ends a human already kept or retired in a chat review (ADR-20261006-c300)."""
    seen = _state(store).get("seen_dead_ends")
    return {s for s in seen if isinstance(s, str)} if isinstance(seen, list) else set()


def _save_review(store: Store, cursor: datetime) -> None:
    """`cursor`: dead ends created after it count as new next time. Chat-seen ones after it stay seen."""
    data: dict = {"last_review_at": cursor.isoformat()}
    keep = sorted(d.id for d in store.load_all("de") if d.id in _seen_dead_ends(store) and d.created_at > cursor)
    if keep:
        data["seen_dead_ends"] = keep
    atomic_write(store.local / STATE, json.dumps(data) + "\n")


def mark_dead_end_seen(store: Store, de_id: str) -> None:
    """A chat review showed this dead end and the human answered keep or wrong: it's no longer new."""
    data = _state(store)
    data["seen_dead_ends"] = sorted(_seen_dead_ends(store) | {de_id})
    atomic_write(store.local / STATE, json.dumps(data) + "\n")


def pending(store: Store) -> tuple[list[DeadEnd], list[requests.SupersedeRequest], list[Invariant]]:
    since = _last_review(store)
    seen = _seen_dead_ends(store)
    dead_ends = sorted(
        (
            d
            for d in store.load_all("de")
            if isinstance(d, DeadEnd)
            and d.status == "ACTIVE"
            and (since is None or d.created_at > since)
            and d.id not in seen
        ),
        key=lambda d: (d.created_at, d.id),  # oldest first, like proposals
    )
    live = requests.pending_supersede_ids(store)
    reqs = sorted(
        (r for r in requests.load_all(store) if r.invariant_id in live),
        key=lambda r: (r.requested_at, r.invariant_id),  # oldest first, like everything else
    )
    proposals = sorted(
        (i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.PROPOSED),
        key=lambda i: (i.created_at, i.id),
    )
    return dead_ends, reqs, proposals


def run(store: Store, cfg: Config) -> Tally:
    tally = Tally()
    started = utcnow()  # dead ends created while reviewing still count as new next time
    previous = _last_review(store)
    dead_ends, reqs, proposals = pending(store)
    config_changed = bool(verifier.check_fingerprints(store.root, cfg))
    if not (config_changed or dead_ends or reqs or proposals):
        typer.echo("Nothing to review.")
        _save_review(store, started)
        return tally
    typer.echo(
        f"To review: {len(proposals)} proposed rule(s), {len(reqs)} supersede request(s), "
        f"{len(dead_ends)} new dead end(s)" + (", runner config changes" if config_changed else "") + "."
    )
    seen: list[DeadEnd] = []  # dead ends actually shown and answered
    cursor = started
    try:
        config_ok = _review_config(store, cfg) if config_changed else True
        _review_dead_ends(store, dead_ends, tally, seen)
        _review_requests(store, cfg, reqs, tally)
        _review_proposals(store, cfg, proposals, config_ok, tally)
    except Quit:
        typer.echo("Stopped. Anything not decided stays waiting.")
        if len(seen) < len(dead_ends):  # quit inside the dead-end list: keep the rest "new"
            cursor = seen[-1].created_at if seen else (previous or datetime.min.replace(tzinfo=started.tzinfo))
    _save_review(store, cursor)
    _summary(tally)
    return tally


def _review_config(store: Store, cfg: Config) -> bool:
    typer.echo("\n== Runner config changes (these control how every locked test runs)")
    shown = show_config_changes(store, cfg)
    if typer.confirm("Confirm these runner config changes?", default=False):
        if verifier.current_fingerprints(store.root, cfg) != shown:
            typer.echo("  the files changed again while you were reviewing them: not confirmed. Run review again.")
            return False
        verifier.confirm_fingerprints(store.root, shown)
        typer.echo("  confirmed.")
        return True
    typer.echo("  not confirmed: approvals are blocked, and every locked rule fails verification until you do.")
    return False


def _review_dead_ends(store: Store, dead_ends: list[DeadEnd], tally: Tally, seen: list[DeadEnd]) -> None:
    if dead_ends:
        typer.echo("\n== Dead ends recorded since your last review (they steer the agent; retire wrong ones)")
    for de in dead_ends:
        typer.echo(f"{de.id} ({de.source}, {de.created_at.date().isoformat()}) scope: {', '.join(de.scope.paths)}")
        typer.echo(f"  tried:  {de.approach}")
        typer.echo(f"  failed: {de.failure_symptom[:300]}")
        if _choice("[k]eep  [w]rong, retire it  [q]uit", "kwq", "k") == "w":
            reason = typer.prompt("  Why is it wrong?", default="marked wrong in review")
            lifecycle.retire_dead_end(store, de.id, reason)
            tally.retired.append(de.id)
        seen.append(de)


def _review_requests(store: Store, cfg: Config, reqs: list[requests.SupersedeRequest], tally: Tally) -> None:
    if reqs:
        typer.echo("\n== Supersede requests (a locked rule would stop running)")
    for req in reqs:
        inv = store.get(req.invariant_id)
        assert isinstance(inv, Invariant)
        show_invariant(store, inv)
        typer.echo(f"  requested: {req.reason} (replacement: {req.replacement_id or 'none'}, {req.requested_at})")
        key = _choice("[a]pprove supersede  [d]ecline request  [s]kip  [q]uit", "adsq", "s")
        if key == "a":
            lifecycle.supersede(store, cfg, req.invariant_id)
            tally.superseded.append(req.invariant_id)
        elif key == "d":
            requests.clear(store, req.invariant_id)
            tally.declined.append(req.invariant_id)
        else:
            tally.skipped.append(req.invariant_id)


def _review_proposals(store: Store, cfg: Config, proposals: list[Invariant], config_ok: bool, tally: Tally) -> None:
    if proposals:
        typer.echo("\n== Proposed rules")
    for inv in proposals:
        typer.echo("")
        show_invariant(store, inv)
        if typer.confirm("Run it now to check it fails without your change?", default=True):
            typer.echo("  " + redgreen.check(store, cfg, inv).line())
        key = _choice("[a]pprove  [r]eject  [s]kip  [q]uit", "arsq", "s")
        if key == "a":
            if not config_ok:
                typer.echo("  can't approve while runner config changes are unconfirmed; skipped.")
                tally.skipped.append(inv.id)
                continue
            try:
                lifecycle.approve(store, cfg, inv.id)
                tally.approved.append(inv.id)
                typer.echo(f"  LOCKED {inv.id}")
            except lifecycle.LifecycleError as exc:
                typer.echo(f"  not approved: {exc}")
                tally.skipped.append(inv.id)
        elif key == "r":
            reason = typer.prompt("  Reason")
            dead = typer.confirm("  Also record as dead end?", default=False)
            out = lifecycle.reject(store, cfg, inv.id, reason, as_dead_end=dead)
            tally.rejected.append(inv.id)
            typer.echo(f"  REJECTED {inv.id}" + (f"; dead end {out['dead_end']}" if "dead_end" in out else ""))
        else:
            tally.skipped.append(inv.id)


def _summary(t: Tally) -> None:
    parts = [
        (f"approved {len(t.approved)}", t.approved),
        (f"rejected {len(t.rejected)}", t.rejected),
        (f"superseded {len(t.superseded)}", t.superseded),
        (f"declined {len(t.declined)}", t.declined),
        (f"dead ends retired {len(t.retired)}", t.retired),
        (f"skipped {len(t.skipped)}", t.skipped),
    ]
    typer.echo("\nReview done: " + ", ".join(label for label, items in parts if items or label.startswith("approved")))
    if t.approved or t.rejected or t.superseded:
        typer.echo("Commit the .seamspec/ changes so teammates and CI see them.")
