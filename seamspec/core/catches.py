"""A record of each time SeamSpec sent the agent back (ADR-20261018-6e1a).

One JSON line per catch in `.seamspec/.local/catches.jsonl` (per machine, never committed): when the
end-of-task check blocked finishing (`stop`), or the commit check refused a commit (`commit`), with
the failing rule ids. `seamspec status` shows the count; the benchmark reads it, since Claude Code's
logs don't show Stop hooks. Writing it never fails the check that caught something.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from .models import utcnow
from .store import Store

CATCHES = "catches.jsonl"
Kind = Literal["stop", "commit"]


def record(store: Store, kind: Kind, ids: list[str]) -> None:
    line = json.dumps({"at": utcnow().isoformat(), "kind": kind, "ids": sorted(ids)})
    try:
        with (store.local / CATCHES).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load(store: Store) -> list[dict[str, Any]]:
    try:
        lines = (store.local / CATCHES).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("kind") in ("stop", "commit"):
            out.append(item)
    return out


def counts(store: Store) -> dict[str, int]:
    found = load(store)
    return {kind: sum(c["kind"] == kind for c in found) for kind in ("stop", "commit")}
