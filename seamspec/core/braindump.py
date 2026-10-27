"""BRAINDUMP.md: a person's scratchpad, sorted by the agent into proposals (SPEC §13, ADR-20261013-d9e4).

The person writes anything above the marker. The in-session agent classifies each item (a rule to
protect, a decision, a failed approach, an exploration, a task) and calls the matching tool; this
module only parses, remembers what each item became, and tidies on request. Model-free (§3).

- **Items** (§13.5): list entries and standalone paragraphs above the marker. A list item continues
  only over indented lines; a paragraph runs to the next blank line, list entry or heading; a fenced
  code block is kept whole with the item it belongs to. Headings, rules and HTML comments are skipped.
- **Ids:** `bd_` + the first 8 hex of the SHA-256 of the whitespace-normalized, lowercased text, so
  reflowing a note keeps its id and editing it makes a new item.
- **What an item became** lives in `.seamspec/.local/braindump.json`, never in the markdown. Only
  `tidy()`, which the person runs, ever touches the part above the marker.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .hashing import normalize_text, sha256_bytes
from .models import utcnow
from .store import Store, atomic_write
from .tree import tree_fingerprint

STATE = "braindump.json"
NUDGE = "nudge.json"
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*\S)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
RULE_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
MANAGED_HEADING = "## Processed (managed by SeamSpec)"
LOG_RE = re.compile(r"^- `bd_[0-9a-f]{8}` → ")  # what `tidy()` writes below the marker
Became = Literal["invariant", "dead_end", "decision", "todo", "exploration", "planned"]
# Set aside without a record. `planned`: a rule whose code doesn't exist yet. It stays in the file,
# is shown to the agent as a rule the user wants, and becomes a proposed rule once the code exists
# (ADR-20261014-5e3a).
DISMISSALS = ("todo", "exploration", "planned")
PLANNED_TEXT_MAX = 200


@dataclass(frozen=True)
class Item:
    id: str
    text: str


def item_id(text: str) -> str:
    return "bd_" + sha256_bytes(normalize_text(text).encode("utf-8"))[:8]


def _human_part(markdown: str, marker: str) -> str:
    return markdown.split(marker, 1)[0]


def below_marker(markdown: str, marker: str) -> list[str]:
    """Lines a person wrote below the marker, where SeamSpec keeps its log and never reads notes:
    anything but blank lines, the managed heading and `tidy()`'s log lines (release rehearsal, 2026-10-24)."""
    _, found, managed = markdown.partition(marker)
    if not found:
        return []
    return [
        ln.strip()
        for ln in managed.splitlines()
        if ln.strip() and ln.strip() != MANAGED_HEADING and not LOG_RE.match(ln.strip())
    ]


def below_marker_note(root: Path, path: str, marker: str) -> str | None:
    """The sentence to show when notes sit below the marker, or None."""
    text = read(root, path)
    stray = below_marker(text, marker) if text is not None else []
    if not stray:
        return None
    return (
        f"{len(stray)} line(s) in {path} are below the `{marker}` line, where SeamSpec keeps its log and doesn't "
        "read notes. Move them above that line to have them sorted."
    )


def _closes(line: str, fence: str) -> bool:
    """A closing fence: the opener's character, at least as many, and nothing after (CommonMark)."""
    stripped = line.strip()
    return len(stripped) >= len(fence) and stripped == fence[0] * len(stripped)


def _parse(markdown: str, marker: str) -> list[tuple[list[str], list[int]]]:
    """Each item above the marker: its parts and the numbers of the lines they came from."""
    lines = _human_part(markdown, marker).splitlines()
    items: list[tuple[list[str], list[int]]] = []
    current: tuple[list[str], list[int]] | None = None
    kind = ""  # "list" | "para" | ""
    fence: str | None = None
    in_comment = False

    def add(n: int, text: str) -> None:
        holder = current if current is not None else items[-1]
        holder[0].append(text)
        holder[1].append(n)

    def start(n: int, text: str) -> tuple[list[str], list[int]]:
        item = ([text], [n])
        items.append(item)
        return item

    for n, raw in enumerate(lines):
        if fence is not None:  # inside a fenced block: kept whole, never parsed
            add(n, raw)
            if _closes(raw, fence):
                fence = None
            continue
        if in_comment:
            in_comment = "-->" not in raw
            continue
        stripped = raw.strip()
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        if opened := FENCE_RE.match(raw):
            fence = opened.group(1)  # the whole opener: a shorter fence inside doesn't close it
            if current is None:  # a code block on its own is an item
                current, kind = start(n, raw), "para"
            else:
                add(n, raw)
            continue
        if not stripped:
            if kind == "para":
                current, kind = None, ""
            continue
        if HEADING_RE.match(raw) or RULE_RE.match(raw):
            current, kind = None, ""
            continue
        if entry := ITEM_RE.match(raw):
            current, kind = start(n, entry.group(1)), "list"
            continue
        if kind == "list" and raw[:1] in (" ", "\t"):
            add(n, stripped)  # an indented line continues the list item
            continue
        if kind == "para":
            add(n, stripped)
            continue
        current, kind = start(n, stripped), "para"  # an unindented line starts a new paragraph
    return items


def parse_items(markdown: str, marker: str) -> list[Item]:
    """The items above the marker, in order (§13.5). Duplicates (same id) are listed once."""
    seen: set[str] = set()
    out: list[Item] = []
    for parts, _ in _parse(markdown, marker):
        text = "\n".join(parts).strip()
        if not text:
            continue
        iid = item_id(text)
        if iid not in seen:
            seen.add(iid)
            out.append(Item(iid, text))
    return out


def _state_path(store: Store) -> Path:
    return store.local / STATE


def state(store: Store) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_state_path(store).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(store: Store, iid: str, became: Became, ref: str | None, text: str = "") -> None:
    """Remember what an item became. Called by the tools that create records from it."""
    data = state(store)
    data[iid] = {"as": became, "ref": ref, "at": utcnow().isoformat(), "preview": " ".join(text.split())[:80]}
    atomic_write(_state_path(store), json.dumps(data, indent=2, sort_keys=True) + "\n")


def location(root: Path, path: str) -> Path | None:
    """Where the notes file is, links followed, or None when that is outside the project: a cloned
    repository's config or link must not make SeamSpec read or write a file elsewhere (#97)."""
    try:
        here, target = root.resolve(), (root / path).resolve()
    except (OSError, RuntimeError, ValueError):  # a link loop
        return None
    return target if here in target.parents else None


def read(root: Path, path: str) -> str | None:
    if (where := location(root, path)) is None:
        return None
    try:
        return where.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def pending(store: Store, path: str, marker: str) -> list[Item]:
    """Items above the marker that haven't become anything yet."""
    text = read(store.root, path)
    if text is None:
        return []
    done = state(store)
    return [i for i in parse_items(text, marker) if i.id not in done]


def dismiss(store: Store, path: str, marker: str, dismissals: list[dict[str, str]]) -> list[str]:
    """Record items as `todo`, `exploration` or `planned`: they stay in the file, and stop being pending."""
    by_id = {i.id: i for i in pending(store, path, marker)}
    done = []
    for d in dismissals:
        iid, kind = d.get("item_id", ""), d.get("as", "")
        if kind not in DISMISSALS:
            raise ValueError(f"{iid}: dismiss as one of {', '.join(DISMISSALS)}, not {kind!r}")
        if iid not in by_id:
            raise KeyError(f"{iid} is not a pending item of {path}")
        record(store, iid, kind, None, by_id[iid].text)  # type: ignore[arg-type]
        done.append(iid)
    return done


def planned(store: Store, path: str, marker: str) -> list[Item]:
    """Notes set aside as planned rules that are still in the file. Deleting the note drops the plan;
    proposing a rule from it (origin_ref = its id) turns it into that rule."""
    text = read(store.root, path)
    if text is None:
        return []
    done = state(store)
    return [i for i in parse_items(text, marker) if done.get(i.id, {}).get("as") == "planned"]


PLANNED_HEADING = (
    "SeamSpec: rules the user planned in their notes (not enforced, no test yet). Build to them. When the "
    'code for one exists and works, propose it as a rule (origin_type="braindump", origin_ref=<its id>):'
)
PLANNED_LISTED = 15


def planned_lines(store: Store, path: str, marker: str) -> list[str]:
    """The planned rules for the agent: a heading, one clipped line each, and a count past the limit.
    Empty when there are none; never raises (it's context, never enforcement)."""
    try:
        items = planned(store, path, marker)
    except Exception:  # noqa: BLE001 - a broken notes file must not break a session start
        return []
    if not items:
        return []
    lines = [PLANNED_HEADING]
    for item in items[:PLANNED_LISTED]:
        flat = " ".join(item.text.split())
        lines.append(f"- {item.id}: {flat if len(flat) <= PLANNED_TEXT_MAX else flat[: PLANNED_TEXT_MAX - 1] + '…'}")
    if len(items) > PLANNED_LISTED:
        lines.append(f"- … and {len(items) - PLANNED_LISTED} more (`seamspec drain --json` lists them all)")
    return lines


def planned_payload(store: Store, path: str, marker: str) -> dict[str, Any] | None:
    """The planned rules for machine-readable context (MCP `get_constraints`, `context --json`), or None.
    Never raises, like `planned_lines()`."""
    try:
        items = planned(store, path, marker)
    except Exception:  # noqa: BLE001 - a broken notes file must not break context
        return None
    return {"note": PLANNED_HEADING, "rules": [{"id": i.id, "text": i.text} for i in items]} if items else None


def note_text(store: Store, path: str, marker: str, iid: str) -> str | None:
    """A note's own text, when it is still in the file."""
    text = read(store.root, path)
    if text is None:
        return None
    return next((i.text for i in parse_items(text, marker) if i.id == iid), None)


def nudge_key(items: list[Item]) -> str:
    return sha256_bytes(",".join(sorted(i.id for i in items)).encode("utf-8"))[:16]


def should_nudge(store: Store, items: list[Item]) -> bool:
    """When what's pending changed since the last nudge, or the project's files did (§13.9). A "no"
    isn't asked again for the same notes and code; but an offer can go unanswered in a chat that
    starts with a task, and a note can wait for code that now exists (hands-on test, ADR-20261014-8a57)."""
    if not items:
        return False
    try:
        last = json.loads((store.local / NUDGE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    if not isinstance(last, dict):
        last = {}
    if last.get("key") != nudge_key(items):
        return True
    code = tree_fingerprint(store.root)
    return code is not None and last.get("code") != code


def remember_nudge(store: Store, items: list[Item]) -> None:
    state = {"key": nudge_key(items), "code": tree_fingerprint(store.root), "at": utcnow().isoformat()}
    atomic_write(store.local / NUDGE, json.dumps(state) + "\n")


def tidy(store: Store, path: str, marker: str) -> int:
    """Move processed items from the person's part into the managed part, as one log line each
    (§13.2, §13.7). The only operation that changes the person's text, and only when they run it.
    Returns how many items moved."""
    text = read(store.root, path)
    if text is None:
        return 0
    done = state(store)
    human, _, managed = text.partition(marker)
    moved = [i for i in parse_items(human, marker) if i.id in done and done[i.id].get("as") != "planned"]
    if not moved:
        return 0
    human = _remove_items(human, marker, {i.id for i in moved})
    log = [_log_line(item.id, done[item.id], item.text) for item in moved]
    managed = managed.rstrip("\n")
    if MANAGED_HEADING not in managed:
        managed += ("\n" if managed else "") + MANAGED_HEADING
    where = location(store.root, path)
    assert where is not None  # read() found it
    atomic_write(where, human.rstrip("\n") + "\n\n" + marker + managed + "\n" + "\n".join(log) + "\n")
    return len(moved)


def _log_line(iid: str, entry: dict[str, Any], text: str) -> str:
    preview = " ".join(text.split())
    preview = preview if len(preview) <= 60 else preview[:59].rstrip() + "…"
    became = entry.get("as", "")
    ref = entry.get("ref")
    what = {"invariant": f"invariant `{ref}`", "dead_end": f"dead end `{ref}`", "decision": f"decision `{ref}`"}.get(
        became, f"dismissed ({became})"
    )
    return f'- `{iid}` → {what} — "{preview}"'


def _remove_items(human: str, marker: str, ids: set[str]) -> str:
    """Remove these items' own lines from the person's part, found by where the parser read them, so
    the same words in a comment, a code example or a longer note stay (#97). Blank lines inside an
    item go with it; everything else is kept byte for byte. A note written twice goes both times."""
    lines = human.splitlines(keepends=True)
    drop: set[int] = set()
    for parts, numbers in _parse(human, marker):
        if item_id("\n".join(parts).strip()) in ids:
            mine = set(numbers)
            drop.update(n for n in range(numbers[0], numbers[-1] + 1) if n in mine or not lines[n].strip())
    return "".join(line for n, line in enumerate(lines) if n not in drop)


TEMPLATE_INTRO = (
    "<!-- Write anything: bullets, paragraphs, pasted snippets. SeamSpec only reads above the marker,"
    " and only the agent's sorting (/seamspec:drain) turns a note into a proposal you then review. -->"
)
