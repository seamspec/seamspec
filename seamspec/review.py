"""`seamspec review`: one interactive pass over everything waiting for a human (SPEC §15, §11).

Order: runner config changes (they gate approvals) → dead ends recorded since the last review
(so wrong ones get retired early, §11.3) → supersede requests → proposed invariants, oldest first,
each with its full test and an optional red-green check (§11.4).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

import typer

from .core import lifecycle, redgreen, requests, testview, verifier
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


RULE_WIDTH = 72
TEXT_MAX = 300  # long origins and reasons are cut here, visibly


def _color() -> bool:
    """Styling only for a real terminal that hasn't opted out (https://no-color.org)."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _style(text: str, **how: bool) -> str:
    return typer.style(text, **how) if _color() else text


def cut(text: str, limit: int = TEXT_MAX) -> str:
    """One line, cut with a visible "…" when it's longer than `limit` (dogfooding finding #7)."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def divider(label: str) -> None:
    """Each item starts with a rule and a line saying where the reviewer is: one item, one block."""
    typer.echo("")
    typer.echo(_style("─" * RULE_WIDTH, dim=True))
    typer.echo(_style(label, bold=True))


def show_invariant(store: Store, inv: Invariant, position: str | None = None) -> None:
    """A rule for the reviewer: summary first, then what its test checks, then the full test (SPEC
    §15.1, ADR-20261011-8013). Everything comes from the record or is read out of the test file;
    nothing the agent wrote *about* its test is shown. The full test always follows: approval means
    the human saw it (§12.4.3 rule 4)."""
    divider(f"{position or f'Rule [{inv.status.value}]'} · {inv.id}")
    typer.echo(f"  Title:  {inv.title}")
    typer.echo(f"  Rule:   {inv.assertion}")
    typer.echo(f"  Where:  {', '.join(inv.scope.paths)}")
    typer.echo(f"  Why:    {inv.origin.type}: {cut(inv.origin.text)}")
    for old_id, title, note in replaces(store, inv):
        typer.echo(f"  Replaces: {old_id} · {title} ({note})")
    harness = store.root / inv.verification.harness_path
    where = f"{inv.verification.harness_path} (runner: {inv.verification.runner})"
    if not harness.is_file():
        typer.echo(f"  Test:   {where}")
        typer.echo(_style("  ! the test file is missing", bold=True))
        return
    view = testview.analyze(harness.read_text(encoding="utf-8"), inv.verification.runner)
    typer.echo(f"  Test:   {where} · {view.facts()}")
    for warning in view.warnings:
        typer.echo(_style(f"  ! {warning}", bold=True))

    if view.checks:
        how = "read from the test file by SeamSpec" if view.parsed else "lines that look like checks"
        typer.echo(f"\n  What this test checks ({how}):")
        for check in view.checks:
            typer.echo(f"    {check.line:>4}  {check.text}")
    typer.echo("\n  The full test (check lines are marked >):")
    marked = view.check_lines
    for number, line in enumerate(view.lines, 1):
        if number in marked:
            typer.echo(_style(f"    {number:>4} > {line}", bold=True))
        else:
            typer.echo(_style(f"    {number:>4} | {line}", dim=True))


def replaces(store: Store, inv: Invariant) -> list[tuple[str, str, str]]:
    """What this rule replaces, for its card, as (id, title, SeamSpec's note): rules already retired
    in its favor, and locked rules with a pending supersede request that names it (dogfooding #10: a
    replacement's screen didn't say what it replaced). The title is the agent's text."""
    asked = {r.invariant_id for r in requests.load_all(store) if r.replacement_id == inv.id}
    asked &= requests.pending_supersede_ids(store)
    lines = []
    for other in sorted(store.load_all("inv"), key=lambda i: i.id):
        if not isinstance(other, Invariant) or other.id == inv.id:
            continue
        if other.id in asked:
            lines.append((other.id, other.title, "still locked; retired when its supersede request is approved"))
        elif other.status == InvStatus.SUPERSEDED and other.superseded_by == inv.id:
            lines.append((other.id, other.title, "retired"))
    return lines


def paired_replacements(store: Store, reqs: list[requests.SupersedeRequest]) -> set[str]:
    """Proposed rules that are the replacement in a pending supersede request. They are decided
    together with that request, never on their own in the proposals list (ADR-20261013-7c2e)."""
    found = (_replacement(store, req) for req in reqs)
    return {rep.id for rep in found if rep is not None and rep.status == InvStatus.PROPOSED}


def _replacement(store: Store, req: requests.SupersedeRequest) -> Invariant | None:
    if not req.replacement_id:
        return None
    try:
        rep = store.get(req.replacement_id)
    except KeyError:
        return None
    return rep if isinstance(rep, Invariant) else None


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
    paired = paired_replacements(store, reqs)  # decided with their supersede request, as one item
    proposals = [p for p in proposals if p.id not in paired]
    config_changed = bool(verifier.check_fingerprints(store.root, cfg))
    if not (config_changed or dead_ends or reqs or proposals):
        typer.echo("Nothing to review.")
        _save_review(store, started)
        return tally
    with_replacement = f" ({len(paired)} with a replacement rule)" if paired else ""
    typer.echo(
        f"To review: {len(proposals)} proposed rule(s), {len(reqs)} supersede request(s){with_replacement}, "
        f"{len(dead_ends)} new dead end(s)" + (", runner config changes" if config_changed else "") + "."
    )
    seen: list[DeadEnd] = []  # dead ends actually shown and answered
    cursor = started
    try:
        config_ok = _review_config(store, cfg) if config_changed else True
        _review_dead_ends(store, dead_ends, tally, seen)
        _review_requests(store, cfg, reqs, config_ok, tally)
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
    for n, de in enumerate(dead_ends, 1):
        divider(f"Dead end {n} of {len(dead_ends)} · {de.id}")
        typer.echo(f"  Recorded: {de.source}, {de.created_at.date().isoformat()}")
        typer.echo(f"  Where:    {', '.join(de.scope.paths)}")
        typer.echo(f"  Tried:    {de.approach}")
        typer.echo(f"  Failed:   {de.failure_symptom}")  # in full: the reason is what the reviewer judges
        if _choice("[k]eep  [w]rong, retire it  [q]uit", "kwq", "k") == "w":
            reason = typer.prompt("  Why is it wrong?", default="marked wrong in review")
            lifecycle.retire_dead_end(store, de.id, reason)
            tally.retired.append(de.id)
        seen.append(de)


def _review_requests(
    store: Store, cfg: Config, reqs: list[requests.SupersedeRequest], config_ok: bool, tally: Tally
) -> None:
    """A supersede request and its replacement are one decision (dogfooding #10, ADR-20261013-7c2e):
    approving locks the replacement first and retires the old rule only then, so stopping at any
    point never leaves the behavior without a rule."""
    if reqs:
        typer.echo("\n== Supersede requests (a locked rule would stop running)")
    for n, req in enumerate(reqs, 1):
        inv = store.get(req.invariant_id)
        assert isinstance(inv, Invariant)
        where = f"Supersede request {n} of {len(reqs)}"
        rep = _replacement(store, req)
        swap = rep is not None and rep.status == InvStatus.PROPOSED
        show_invariant(store, inv, f"{where}: the rule that would stop running")
        typer.echo(f"\n  Requested: {req.reason} ({req.requested_at})")
        if swap:
            assert rep is not None
            show_invariant(store, rep, f"{where}: its replacement")
            typer.echo("")
            if typer.confirm("Run the replacement now to check it fails without your change?", default=True):
                _show_red_green(redgreen.check(store, cfg, rep))
            typer.echo(f"  One decision: approving locks {rep.id} and then retires {inv.id}.")
            keys, prompt = "adsq", "[a]pprove the replacement and retire the old rule  [d]ecline  [s]kip  [q]uit"
        elif rep is not None and rep.status == InvStatus.LOCKED:
            typer.echo(f"  Replacement: {rep.id} · {rep.title} (already locked)")
            keys, prompt = "adsq", "[a]pprove: retire the old rule  [d]ecline request  [s]kip  [q]uit"
        elif req.replacement_id:
            state = rep.status.value if rep is not None else "missing"
            typer.echo(
                f"  Replacement: {req.replacement_id} is {state}, so this request can't be approved as it stands."
            )
            typer.echo("  Decline it and ask for a new request, or retire the rule yourself: `seamspec supersede`.")
            keys, prompt = "dsq", "[d]ecline request  [s]kip  [q]uit"
        else:
            typer.echo(_style("  No replacement: after this, no rule protects this behavior.", bold=True))
            keys, prompt = "adsq", "[a]pprove: retire the rule  [d]ecline request  [s]kip  [q]uit"

        key = _choice(prompt, keys, "s")
        if key == "a":
            _approve_request(store, cfg, req, rep if swap else None, config_ok, tally)
        elif key == "d":
            requests.clear(store, req.invariant_id)
            tally.declined.append(req.invariant_id)
            if swap and typer.confirm(f"  Also reject the replacement {req.replacement_id}?", default=True):
                assert rep is not None
                lifecycle.reject(store, cfg, rep.id, f"the supersede request for {inv.id} was declined")
                tally.rejected.append(rep.id)
                typer.echo(f"  REJECTED {rep.id}")
        else:
            tally.skipped.append(req.invariant_id)


def _approve_request(
    store: Store, cfg: Config, req: requests.SupersedeRequest, rep: Invariant | None, config_ok: bool, tally: Tally
) -> None:
    """`rep`: the proposed replacement to lock first, or None when there is nothing to lock."""
    if rep is not None:
        if not config_ok:
            typer.echo("  can't approve while runner config changes are unconfirmed; nothing changed, skipped.")
            tally.skipped.append(req.invariant_id)
            return
        try:
            lifecycle.approve(store, cfg, rep.id)
        except lifecycle.LifecycleError as exc:
            typer.echo(f"  the replacement was not approved, so {req.invariant_id} stays locked: {exc}")
            tally.skipped.append(req.invariant_id)
            return
        tally.approved.append(rep.id)
        typer.echo(f"  LOCKED {rep.id}")
    try:
        out = lifecycle.supersede(store, cfg, req.invariant_id)
    except lifecycle.LifecycleError as exc:
        typer.echo(f"  {req.invariant_id} was not retired and stays locked: {exc}")
        tally.skipped.append(req.invariant_id)
        return
    tally.superseded.append(req.invariant_id)
    by = f" (replaced by {out['superseded_by']})" if out["superseded_by"] else " (no replacement)"
    typer.echo(f"  SUPERSEDED {req.invariant_id}{by}")


def _show_red_green(result: redgreen.RedGreen) -> None:
    typer.echo(_style("  " + result.line(), bold=True))
    if result.hint():
        typer.echo(f"  {result.hint()}")


def _review_proposals(store: Store, cfg: Config, proposals: list[Invariant], config_ok: bool, tally: Tally) -> None:
    if proposals:
        typer.echo("\n== Proposed rules")
    for n, inv in enumerate(proposals, 1):
        show_invariant(store, inv, f"Proposed rule {n} of {len(proposals)}")
        typer.echo("")
        if typer.confirm("Run it now to check it fails without your change?", default=True):
            _show_red_green(redgreen.check(store, cfg, inv))
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
