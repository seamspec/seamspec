"""The part of the code a rule is about (SPEC §16.1, §15.2).

The session-start summary and the generated spec group rules the same way, by the folder their
scope points at, so the two always agree.
"""

from __future__ import annotations

from pathlib import Path

ROOT_AREA = "(repository root)"


def area(paths: list[str], root: Path) -> str:
    """The folder a scope is about (Copilot, #41). With a glob: the whole path segments before the
    first one that holds a glob (`src/billing/**` and `src/billing/gen*.py` -> `src/billing`,
    `.github/**` -> `.github`). Without one, the path names a folder or a file (gitignore rules):
    a folder that exists, or one written with a trailing `/`, is its own area; a file's area is its folder."""
    first = " ".join(paths[0].split()).lstrip("!/") if paths else ""
    parts = first.split("/")
    globbed = next((i for i, part in enumerate(parts) if any(c in part for c in "*?[")), None)
    if globbed is not None:
        found = "/".join(parts[:globbed])
    elif first.endswith("/") or (root / first).is_dir():
        found = first.rstrip("/")
    else:
        found = "/".join(parts[:-1])
    return found or ROOT_AREA
