"""Which invariants and dead ends apply to a set of files (SPEC §19.6, §11.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import DeadEnd, Invariant, InvStatus
from .root import to_rel
from .scope import matches
from .store import Store

DEFAULT_LIMIT = 20


@dataclass
class ConstraintSet:
    files: list[str]
    locked: list[Invariant] = field(default_factory=list)
    proposed: list[Invariant] = field(default_factory=list)
    dead_ends: list[DeadEnd] = field(default_factory=list)
    omitted: int = 0  # matches beyond the per-kind limit, so a cut list is never silent

    @property
    def empty(self) -> bool:
        """Nothing that should reach the agent at edit time (proposed rules don't gate anything)."""
        return not (self.locked or self.dead_ends)

    def render(self) -> str:
        """Body lines only; callers add their own header (e.g. "SeamSpec: <file> is governed by:").
        Dead ends read as history, not orders, so the agent can still reconsider (§11.3)."""
        lines: list[str] = []
        for inv in self.locked:
            adr = f" ({inv.adr_id})" if inv.adr_id else ""
            lines.append(f"- [LOCKED] {inv.id}: {inv.assertion}{adr}")
        for inv in self.proposed:
            lines.append(f"- [PROPOSED, awaiting human review] {inv.id}: {inv.assertion}")
        if self.dead_ends:
            lines.append("Previously tried and failed:")
            for de in self.dead_ends:
                symptom = de.failure_symptom[:200]
                lines.append(
                    f"- {de.id}: tried {de.approach}; failed previously because: {symptom} "
                    f"(recorded {de.created_at.date().isoformat()})"
                )
        if self.omitted:
            lines.append(f"... and {self.omitted} more. Run `seamspec context` on fewer files to see them.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON shape shared by `seamspec context --json` and the MCP `get_constraints` tool."""
        return {
            "files": self.files,
            "locked": [i.model_dump(mode="json") for i in self.locked],
            "proposed": [i.model_dump(mode="json") for i in self.proposed],
            "dead_ends": [d.model_dump(mode="json") for d in self.dead_ends],
            "omitted": self.omitted,
        }


def constraints_for(store: Store, files: list[str], limit: int = DEFAULT_LIMIT) -> ConstraintSet:
    rels = [r for r in (to_rel(store.root, f) for f in files) if r]
    cs = ConstraintSet(files=rels)

    def hit(paths: list[str]) -> bool:
        return any(matches(paths, r) for r in rels)

    for inv in store.load_all("inv"):
        assert isinstance(inv, Invariant)
        if not hit(inv.scope.paths):
            continue
        if inv.status == InvStatus.LOCKED:
            cs.locked.append(inv)
        elif inv.status == InvStatus.PROPOSED:
            cs.proposed.append(inv)
    cs.dead_ends = [
        d for d in store.load_all("de") if isinstance(d, DeadEnd) and d.status == "ACTIVE" and hit(d.scope.paths)
    ]

    for name in ("locked", "proposed", "dead_ends"):
        items = getattr(cs, name)
        cs.omitted += max(0, len(items) - limit)
        setattr(cs, name, items[:limit])
    return cs
