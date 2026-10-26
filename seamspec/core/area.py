"""The part of the code a rule is about (SPEC §16.1, §15.2).

The session-start summary and the generated spec group rules the same way, by the folder their
scope points at. One difference: for a scope written without a glob or a trailing slash, the summary
looks on disk to see whether it names a folder. The generated spec never looks on disk: its output
must depend on the ledger alone, or a written copy would differ between two machines (Copilot, #58).
"""

from __future__ import annotations

from pathlib import Path

ROOT_AREA = "(repository root)"


def area(paths: list[str], root: Path | None = None) -> str:
    """The folder a scope is about (Copilot, #41). With a glob: the whole path segments before the
    first one that holds a glob (`src/billing/**` and `src/billing/gen*.py` -> `src/billing`,
    `.github/**` -> `.github`). Without one, the path names a folder or a file (gitignore rules):
    one written with a trailing `/` is its own area; otherwise it is read as a file, whose area is
    its folder. With `root`, a path that is a folder on disk is also its own area; without it, the
    answer comes from the scope text alone."""
    first = " ".join(paths[0].split()).lstrip("!/") if paths else ""
    parts = first.split("/")
    globbed = next((i for i, part in enumerate(parts) if any(c in part for c in "*?[")), None)
    if globbed is not None:
        found = "/".join(parts[:globbed])
    elif first.endswith("/") or (root is not None and (root / first).is_dir()):
        found = first.rstrip("/")
    else:
        found = "/".join(parts[:-1])
    return found or ROOT_AREA
