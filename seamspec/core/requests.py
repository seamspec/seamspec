"""Supersede requests made by the agent, waiting for a human (SPEC §11.2).

One file per invariant in `.seamspec/.local/requests/`; a newer request for the same invariant
replaces the older one. A declined request leaves a note in `.seamspec/.local/declined/`, so the
agent hears that a person chose to keep the rule (ADR-20261024-6f0c); a new request replaces it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .models import InvStatus, utcnow
from .store import Store, atomic_write


@dataclass
class SupersedeRequest:
    invariant_id: str
    reason: str
    replacement_id: str | None
    requested_at: str


@dataclass
class Declined:
    invariant_id: str
    declined_at: str
    reason: str = ""  # the person's, when they gave one
    request: str = ""  # what the agent had asked for


def _folder(store: Store):
    return store.local / "requests"


def _declined_folder(store: Store):
    return store.local / "declined"


def save(store: Store, req: SupersedeRequest) -> None:
    store.path_for(req.invariant_id)  # validates the id before it becomes a file name
    atomic_write(_folder(store) / f"{req.invariant_id}.json", json.dumps(asdict(req), indent=2) + "\n")
    (_declined_folder(store) / f"{req.invariant_id}.json").unlink(missing_ok=True)  # asked again


def new(invariant_id: str, reason: str, replacement_id: str | None) -> SupersedeRequest:
    return SupersedeRequest(invariant_id, reason, replacement_id, _now())


def load_all(store: Store) -> list[SupersedeRequest]:
    folder = _folder(store)
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("inv_*.json")):
        try:
            out.append(SupersedeRequest(**json.loads(p.read_text(encoding="utf-8"))))
        except (ValueError, TypeError):
            continue
    return out


def get(store: Store, invariant_id: str) -> SupersedeRequest | None:
    return next((r for r in load_all(store) if r.invariant_id == invariant_id), None)


def clear(store: Store, invariant_id: str) -> None:
    store.path_for(invariant_id)
    (_folder(store) / f"{invariant_id}.json").unlink(missing_ok=True)


def decline(store: Store, invariant_id: str, reason: str = "") -> None:
    """A person declined the request: drop it, and remember that the rule stays."""
    req = get(store, invariant_id)
    note = Declined(invariant_id, _now(), reason.strip(), req.reason if req else "")
    store.path_for(invariant_id)
    atomic_write(_declined_folder(store) / f"{invariant_id}.json", json.dumps(asdict(note), indent=2) + "\n")
    clear(store, invariant_id)


def declined(store: Store) -> dict[str, Declined]:
    """Declines that still apply: the rule is still LOCKED and nobody has asked again since."""
    folder = _declined_folder(store)
    out: dict[str, Declined] = {}
    for p in sorted(folder.glob("inv_*.json")) if folder.is_dir() else []:
        try:
            note = Declined(**json.loads(p.read_text(encoding="utf-8")))
            if store.get(note.invariant_id).status == InvStatus.LOCKED:
                out[note.invariant_id] = note
        except (ValueError, TypeError, KeyError):
            continue
    return out


def declined_lines(store: Store, ids: Iterable[str] | None = None) -> list[str]:
    """What the agent is told about each decline (for every LOCKED rule, or only `ids`)."""
    wanted = None if ids is None else set(ids)
    lines = []
    for inv_id, note in declined(store).items():
        if wanted is not None and inv_id not in wanted:
            continue
        why = f" Their reason: {' '.join(note.reason.split())[:200]}." if note.reason else ""
        lines.append(
            f"- A person declined the request to retire {inv_id} ({store.get(inv_id).title}) on "
            f"{note.declined_at[:10]}.{why} Keep the behavior it protects: restore it if your change broke it, "
            "and don't ask to change it again unless the user asks for that change."
        )
    return lines


def _now() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def pending_supersede_ids(store: Store) -> set[str]:
    """Invariants with a request that still applies (the invariant is still LOCKED)."""
    pending = set()
    for req in load_all(store):
        try:
            if store.get(req.invariant_id).status == InvStatus.LOCKED:
                pending.add(req.invariant_id)
        except KeyError:
            continue
    return pending
