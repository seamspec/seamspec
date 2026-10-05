"""Supersede requests made by the agent, waiting for a human (SPEC §11.2).

One file per invariant in `.seamspec/.local/requests/`; a newer request for the same invariant
replaces the older one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .models import InvStatus, utcnow
from .store import Store, atomic_write


@dataclass
class SupersedeRequest:
    invariant_id: str
    reason: str
    replacement_id: str | None
    requested_at: str


def _folder(store: Store):
    return store.local / "requests"


def save(store: Store, req: SupersedeRequest) -> None:
    store.path_for(req.invariant_id)  # validates the id before it becomes a file name
    atomic_write(_folder(store) / f"{req.invariant_id}.json", json.dumps(asdict(req), indent=2) + "\n")


def new(invariant_id: str, reason: str, replacement_id: str | None) -> SupersedeRequest:
    return SupersedeRequest(invariant_id, reason, replacement_id, utcnow().isoformat().replace("+00:00", "Z"))


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
