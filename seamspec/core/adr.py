"""Architecture Decision Records: Markdown with a small frontmatter block (SPEC §10.3).

Frontmatter values are written as JSON (valid YAML flow style), so no YAML library is needed:
`scopes: ["src/queue/**"]`, `supersedes: null`. Trailing `# comments` on unquoted values are ignored,
so hand-written ADRs in the same format (e.g. docs/adr/) parse too.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from .store import Store, atomic_write

AdrStatus = Literal["PROPOSED", "ACCEPTED", "SUPERSEDED", "REJECTED"]
ADR_ID_RE = re.compile(r"^ADR-[0-9]{8}-[a-f0-9]{4}$")
FIELDS = ("id", "title", "status", "date", "scopes", "invariants", "supersedes", "superseded_by")


class AdrError(RuntimeError):
    pass


@dataclass
class Adr:
    id: str
    title: str
    status: AdrStatus
    date: str
    scopes: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None
    body: str = ""
    path: Path | None = None


def slugify(title: str, max_len: int = 50) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "decision"


def _folder(store: Store) -> Path:
    return store.base / "adrs"


def new_id(store: Store, today: date | None = None) -> str:
    stamp = (today or date.today()).strftime("%Y%m%d")
    existing = {a.id for a in load_all(store)}
    while True:
        candidate = f"ADR-{stamp}-{secrets.token_hex(2)}"
        if candidate not in existing:
            return candidate


def _render(adr: Adr) -> str:
    meta = {
        "id": adr.id,
        "title": adr.title,
        "status": adr.status,
        "date": adr.date,
        "scopes": adr.scopes,
        "invariants": adr.invariants,
        "supersedes": adr.supersedes,
        "superseded_by": adr.superseded_by,
    }
    lines = ["---"]
    for key in FIELDS:
        value = meta[key]
        plain = isinstance(value, str) and key in ("id", "status", "date")
        lines.append(f"{key}: {value if plain else json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + adr.body.strip() + "\n"


def _parse_value(raw: str):
    raw = raw.strip()
    if raw[:1] in ('"', "[", "{") or raw in ("null", "true", "false"):
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return raw.split(" #", 1)[0].strip()


def parse(text: str, path: Path | None = None) -> Adr:
    if not text.startswith("---\n"):
        raise AdrError(f"{path}: missing frontmatter")
    try:
        head, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise AdrError(f"{path}: unterminated frontmatter") from exc
    meta = {}
    for line in head.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, raw = line.split(":", 1)
            meta[key.strip()] = _parse_value(raw)
    missing = [k for k in ("id", "title", "status", "date") if not meta.get(k)]
    if missing:
        raise AdrError(f"{path}: frontmatter lacks {', '.join(missing)}")
    if not ADR_ID_RE.match(str(meta["id"])):
        raise AdrError(f"{path}: bad ADR id {meta['id']!r}")
    if meta["status"] not in ("PROPOSED", "ACCEPTED", "SUPERSEDED", "REJECTED"):
        raise AdrError(f"{path}: bad status {meta['status']!r}")
    return Adr(
        id=str(meta["id"]),
        title=str(meta["title"]),
        status=meta["status"],
        date=str(meta["date"]),
        scopes=list(meta.get("scopes") or []),
        invariants=list(meta.get("invariants") or []),
        supersedes=meta.get("supersedes") or None,
        superseded_by=meta.get("superseded_by") or None,
        body=body.strip(),
        path=path,
    )


def load_all(store: Store) -> list[Adr]:
    folder = _folder(store)
    if not folder.is_dir():
        return []
    return [parse(p.read_text(encoding="utf-8"), p) for p in sorted(folder.glob("ADR-*.md"))]


def get(store: Store, adr_id: str) -> Adr:
    if not ADR_ID_RE.match(adr_id):
        raise KeyError(adr_id)
    for p in _folder(store).glob(f"{adr_id}-*.md"):
        return parse(p.read_text(encoding="utf-8"), p)
    raise KeyError(adr_id)


def create(
    store: Store,
    title: str,
    context: str,
    decision: str,
    consequences: list[str],
    scopes: list[str],
    invariants: list[tuple[str, str]] | None = None,  # (id, assertion)
    status: AdrStatus = "PROPOSED",
    today: date | None = None,
) -> Adr:
    adr_id = new_id(store, today)
    inv_lines = "\n".join(f"* `{i}` — {a}" for i, a in (invariants or [])) or "None."
    cons_lines = "\n".join(f"* {c}" for c in consequences) or "None recorded."
    body = (
        f"# {adr_id}: {title}\n\n## Context\n{context.strip()}\n\n## Decision\n{decision.strip()}\n\n"
        f"## Enforced Invariants\n{inv_lines}\n\n## Consequences\n{cons_lines}"
    )
    adr = Adr(
        id=adr_id,
        title=title,
        status=status,
        date=(today or date.today()).isoformat(),
        scopes=scopes,
        invariants=[i for i, _ in (invariants or [])],
        body=body,
        path=_folder(store) / f"{adr_id}-{slugify(title)}.md",
    )
    assert adr.path is not None
    atomic_write(adr.path, _render(adr))
    return adr


def set_status(store: Store, adr_id: str, status: AdrStatus, superseded_by: str | None = None) -> Adr:
    adr = get(store, adr_id)
    adr.status = status
    if superseded_by is not None:
        adr.superseded_by = superseded_by
    assert adr.path is not None
    atomic_write(adr.path, _render(adr))
    return adr


def summary(store: Store) -> str:
    """One line per ADR (MCP resource `seamspec://adrs`, §14.2)."""
    lines = [f"{a.id}: {a.title} [{a.status}] (scopes: {', '.join(a.scopes) or '-'})" for a in load_all(store)]
    return "\n".join(lines) or "No ADRs recorded."
