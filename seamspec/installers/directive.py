"""The SeamSpec block in CLAUDE.md (SPEC §18, ADR-20261005-c41d).

`init` owns only the text between the markers. Everything outside them is the user's and is
never changed. Re-running `init` replaces the block in place.
"""

from __future__ import annotations

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


def merge(text: str) -> str:
    """Return `text` with the managed block inserted or replaced; other content untouched."""
    block = render_block()
    span = _find_block(text)
    if span is not None:
        start, end = span  # `end` is just past the END line's newline
        return text[:start] + block + "\n" + text[end:]
    if not text.strip():
        return block + "\n"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block + "\n"


def install(root: Path) -> str:
    """Write the block into CLAUDE.md. Returns 'created', 'updated' or 'unchanged'."""
    path = root / "CLAUDE.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    new = merge(old or "")
    if old == new:
        return "unchanged"
    atomic_write(path, new)
    return "created" if old is None else "updated"


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
