"""Auto-run consent and repo trust (SPEC §12.4.5, §12.4.6).

There is no sandbox, so the control is *who decides when code runs*:

- **Consent** (per machine, asked once at `init`): may SeamSpec run approved tests automatically
  (Stop hook, pre-commit)?
- **Trust** (per clone, like `direnv allow`): the runner commands, their env and, with
  `trust_level = "harness"`, every LOCKED test, as a human last confirmed them. A fresh clone, or a
  change to any of these from upstream, is untrusted until `seamspec trust`.

Both files live in `.seamspec/.local/` and are never committed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .hashing import sha256_bytes
from .models import Invariant, InvStatus, utcnow
from .store import Store, atomic_write

CONSENT = "consent.json"
TRUST = "trust.json"


def _now() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def _read(store: Store, name: str) -> dict[str, Any] | None:
    path = store.local / name
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# --- consent ---------------------------------------------------------------------------------------


def record_consent(store: Store, auto_run: bool, actor: str) -> None:
    atomic_write(store.local / CONSENT, json.dumps({"auto_run": auto_run, "by": actor, "at": _now()}, indent=2) + "\n")


def consent_given(store: Store) -> bool:
    data = _read(store, CONSENT)
    return bool(data and data.get("auto_run") is True)


# --- trust -----------------------------------------------------------------------------------------


def locked_harnesses(store: Store) -> dict[str, str]:
    """inv id -> approved harness hash, for every LOCKED invariant."""
    out = {}
    for inv in store.load_all("inv"):
        if isinstance(inv, Invariant) and inv.status == InvStatus.LOCKED and inv.verification.harness_sha256:
            out[inv.id] = inv.verification.harness_sha256
    return out


def trust_hash(cfg: Config, harnesses: dict[str, str]) -> str:
    """What a human trusts: every runner setting (incl. env), env passthrough and, at
    `trust_level = "harness"`, the LOCKED tests too."""
    payload: dict[str, Any] = {
        "runners": {name: r.model_dump(mode="json") for name, r in sorted(cfg.runners.items())},
        "env_passthrough": sorted(cfg.execution.env_passthrough),
        "level": cfg.execution.trust_level,
    }
    if cfg.execution.trust_level == "harness":
        payload["harnesses"] = dict(sorted(harnesses.items()))
    return sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


@dataclass
class TrustState:
    trusted: bool
    reason: str  # why not trusted, or "" when trusted
    by: str | None = None
    at: str | None = None
    new_or_changed_tests: list[str] = field(default_factory=list)  # since the last trust


def state(store: Store, cfg: Config) -> TrustState:
    harnesses = locked_harnesses(store)
    record = _read(store, TRUST)
    if record is None:
        return TrustState(False, "this clone has never been trusted", new_or_changed_tests=sorted(harnesses))
    seen = record.get("harnesses") if isinstance(record.get("harnesses"), dict) else {}
    changed = sorted(i for i, h in harnesses.items() if seen.get(i) != h)
    by, at = record.get("by"), record.get("at")
    if record.get("hash") != trust_hash(cfg, harnesses):
        if cfg.execution.trust_level == "harness" and changed:
            reason = f"{len(changed)} locked test(s) are new or changed since you last trusted this clone"
        else:
            reason = "runner commands or their environment changed since you last trusted this clone"
        return TrustState(False, reason, by, at, changed)
    return TrustState(True, "", by, at, changed)


def grant(store: Store, cfg: Config, actor: str) -> None:
    harnesses = locked_harnesses(store)
    record = {"by": actor, "at": _now(), "hash": trust_hash(cfg, harnesses), "harnesses": harnesses}
    atomic_write(store.local / TRUST, json.dumps(record, indent=2, sort_keys=True) + "\n")


def execution_permitted(store: Store, cfg: Config) -> tuple[bool, str]:
    """May SeamSpec run LOCKED tests on its own (Stop hook, pre-commit)? (allowed, why not)"""
    if cfg.mode == "advisory":
        return False, "advisory mode never runs tests automatically"
    if not consent_given(store):
        return False, "automatic test runs were not allowed on this machine (re-run `seamspec init`)"
    st = state(store, cfg)
    if not st.trusted:
        return False, f"{st.reason}. Run `seamspec trust`"
    return True, ""
