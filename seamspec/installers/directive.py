"""The SeamSpec block in CLAUDE.md (SPEC §18, ADR-20261005-c41d).

`init` owns only the text between the markers. Everything outside them is the user's and is
never changed. Re-running `init` replaces the block in place.

A line someone wrote *inside* the markers is not SeamSpec's either, whatever the marker says: in
dogfooding an agent put the owner's own instruction right after the begin marker, and the next
`init` would have deleted it silently. So before replacing the block, `init` keeps every line in it
that SeamSpec never shipped, by moving it above the block (ADR-20261011-b1c8). SeamSpec's own older
wording is recognised from `templates/directive_known_lines.txt`, so an upgrade rescues nothing.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

from ..core.store import atomic_write

BEGIN = "<!-- seamspec:begin (managed by `seamspec init`; edit outside these markers) -->"
BEGIN_PREFIX = "<!-- seamspec:begin"
END = "<!-- seamspec:end -->"


class DirectiveError(RuntimeError):
    pass


def directive_text() -> str:
    return files("seamspec.templates").joinpath("directive.md").read_text("utf-8").strip()


def render_block() -> str:
    return f"{BEGIN}\n{directive_text()}\n{END}"


KNOWN_LINES = "directive_known_lines.txt"


def _key(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


def known_lines() -> set[str]:
    """Keys of every line SeamSpec has shipped in its block, plus the current template's."""
    recorded = files("seamspec.templates").joinpath(KNOWN_LINES).read_text("utf-8").splitlines()
    keys = {ln.strip() for ln in recorded if ln.strip() and not ln.startswith("#")}
    return keys | {_key(ln) for ln in directive_text().splitlines() if ln.strip()}


def foreign_lines(block: str) -> list[str]:
    """Lines inside a managed block that SeamSpec never shipped: someone else wrote them there."""
    known = known_lines()
    inner = [ln for ln in block.splitlines() if not ln.strip().startswith(BEGIN_PREFIX) and ln.strip() != END]
    return [ln.rstrip() for ln in inner if ln.strip() and _key(ln) not in known]


def _find_block(text: str) -> tuple[int, int] | None:
    """(start, end) offsets of the managed block, end exclusive; None if absent."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith(BEGIN_PREFIX)]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise DirectiveError(
            "CLAUDE.md has unbalanced or repeated SeamSpec markers. Fix them by hand: keep exactly one "
            f"'{BEGIN_PREFIX} ...' line and one '{END}' line after it."
        )
    offset = [0]
    for ln in lines:
        offset.append(offset[-1] + len(ln))
    return offset[starts[0]], offset[ends[0] + 1]


def merge_keeping(text: str) -> tuple[str, list[str]]:
    """`text` with the managed block inserted or replaced, and the lines that were kept: anything
    inside the old block that isn't SeamSpec's is moved above the block, in its original order."""
    block = render_block()
    span = _find_block(text)
    if span is not None:
        start, end = span  # `end` is just past the END line's newline
        kept = foreign_lines(text[start:end])
        before = text[:start]
        if kept:
            gap = "" if not before or before.endswith("\n\n") else ("\n" if before.endswith("\n") else "\n\n")
            before += gap + "\n".join(kept) + "\n\n"
        return before + block + "\n" + text[end:], kept
    if not text.strip():
        return block + "\n", []
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block + "\n", []


def merge(text: str) -> str:
    """Return `text` with the managed block inserted or replaced; other content untouched."""
    return merge_keeping(text)[0]


def install_keeping(root: Path) -> tuple[str, list[str]]:
    """Write the block into CLAUDE.md. Returns ('created' | 'updated' | 'unchanged', lines kept)."""
    path = root / "CLAUDE.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    new, kept = merge_keeping(old or "")
    if old == new:
        return "unchanged", []
    atomic_write(path, new)
    return ("created" if old is None else "updated"), kept


def install(root: Path) -> str:
    """Write the block into CLAUDE.md. Returns 'created', 'updated' or 'unchanged'."""
    return install_keeping(root)[0]


def foreign_in(root: Path) -> list[str]:
    """Lines currently inside CLAUDE.md's block that aren't SeamSpec's (for `doctor`)."""
    path = root / "CLAUDE.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        span = _find_block(text)
    except DirectiveError:
        return []
    return foreign_lines(text[span[0] : span[1]]) if span else []


def drift(root: Path) -> bool:
    """True if CLAUDE.md's block is missing or differs from the packaged template (for `doctor`)."""
    path = root / "CLAUDE.md"
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8")
    try:
        span = _find_block(text)
    except DirectiveError:
        return True
    return span is None or text[span[0] : span[1]].rstrip("\n") != render_block()


def record_known_lines() -> int:
    """Add the current template's lines to the known-lines file (append-only). Returns how many were new."""
    path = Path(__file__).resolve().parents[1] / "templates" / KNOWN_LINES
    text = path.read_text(encoding="utf-8")
    have = {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")}
    new = sorted({_key(ln) for ln in directive_text().splitlines() if ln.strip()} - have)
    if new:
        atomic_write(path, text + "\n".join(new) + "\n")
    return len(new)


if __name__ == "__main__":
    print(f"{record_known_lines()} new line(s) recorded in templates/{KNOWN_LINES}")
