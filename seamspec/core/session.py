"""Per-session hook state in `.seamspec/.local/sessions/` (SPEC §7.2, §16.1).

- `acknowledged`: (file, ledger revision) pairs the agent has already been shown constraints for,
  so edit-time context appears once per file per ledger version, not on every edit.
- `stop_retries`: how often the Stop gate has blocked, per user prompt. A new prompt gets a fresh
  budget, so `verify.max_stop_retries` caps one task, not the whole session.
- `last_green_fingerprint`: the tree fingerprint of the last all-green Stop run, to skip re-runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .store import Store, atomic_write

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass
class SessionState:
    session_id: str
    acknowledged: list[str] = field(default_factory=list)
    stop_retries: dict[str, int] = field(default_factory=dict)
    last_green_fingerprint: str | None = None

    @staticmethod
    def _path(store: Store, session_id: str):
        name = _SAFE.sub("_", session_id)[:128] or "unknown"
        return store.local / "sessions" / f"{name}.json"

    @classmethod
    def load(cls, store: Store, session_id: str) -> SessionState:
        path = cls._path(store, session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                session_id=session_id,
                acknowledged=[str(x) for x in data.get("acknowledged", [])],
                stop_retries={str(k): int(v) for k, v in dict(data.get("stop_retries", {})).items()},
                last_green_fingerprint=data.get("last_green_fingerprint"),
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return cls(session_id=session_id)

    def save(self, store: Store) -> None:
        atomic_write(self._path(store, self.session_id), json.dumps(asdict(self), indent=2) + "\n")
