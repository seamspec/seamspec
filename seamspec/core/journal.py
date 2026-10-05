"""Approval journal and the unjournaled-change check (SPEC §11.1).

Every status change made through the CLI appends a line to `.seamspec/.local/journal.jsonl`.
At Stop and pre-commit, each invariant's status is compared with git `HEAD`; a change that the
journal can't explain is flagged. Not tamper-proof (an agent with a shell could write the journal
too), but it turns a silent retirement into a visible warning.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict, deque
from pathlib import Path

from .models import utcnow
from .store import Store

JOURNAL = "journal.jsonl"
BASELINE_ABSENT = "PROPOSED"  # a record new since HEAD starts from PROPOSED: proposing needs no entry


def append(store: Store, record_id: str, old: str, new: str, actor: str) -> None:
    line = {"id": record_id, "from": old, "to": new, "actor": actor, "at": utcnow().isoformat().replace("+00:00", "Z")}
    with open(store.local / JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def entries(store: Store) -> list[dict]:
    path = store.local / JOURNAL
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and {"id", "from", "to"} <= item.keys():
            out.append(item)
    return out


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None


def head_statuses(root: Path) -> dict[str, str]:
    """Invariant statuses as committed at HEAD. Empty if there is no git repo or no commit yet."""
    prefix = _git(root, "rev-parse", "--show-prefix")
    if prefix is None or prefix.returncode != 0:
        return {}
    folder = f"{prefix.stdout.strip()}.seamspec/invariants/"
    listing = _git(root, "ls-tree", "-r", "--name-only", "--full-tree", "HEAD", "--", folder)
    if listing is None or listing.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for name in listing.stdout.splitlines():
        if not name.endswith(".json"):
            continue
        shown = _git(root, "show", f"HEAD:{name}")
        if shown is None or shown.returncode != 0:
            continue
        try:
            data = json.loads(shown.stdout)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            out[data["id"]] = str(data.get("status"))
    return out


def _explained(edges: set[tuple[str, str]], start: str, goal: str) -> bool:
    """True if journaled transitions lead from `start` to `goal` (e.g. PROPOSED → LOCKED → SUPERSEDED)."""
    graph: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    seen, queue = {start}, deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            return True
        for nxt in graph[node] - seen:
            seen.add(nxt)
            queue.append(nxt)
    return False


def unjournaled_changes(store: Store) -> list[str]:
    """Human-readable problems; empty when every status change since HEAD went through the CLI."""
    head = head_statuses(store.root)
    now = {inv.id: inv.status.value for inv in store.load_all("inv")}
    edges: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for e in entries(store):
        edges[e["id"]].add((e["from"], e["to"]))

    problems: list[str] = []
    for inv_id, status in sorted(now.items()):
        before = head.get(inv_id, BASELINE_ABSENT)
        if status == before:
            continue
        # Moving *back* to PROPOSED (e.g. LOCKED → PROPOSED) would drop a rule from verification;
        # the CLI never does it, so the journal can't explain it and it is flagged below.
        if not _explained(edges[inv_id], before, status):
            where = "is new and already" if inv_id not in head else f"was changed from {before} to"
            problems.append(
                f"{inv_id} {where} {status} outside the SeamSpec CLI. "
                "Revert it, or ask the user to run `seamspec review`."
            )
    for inv_id, status in sorted(head.items()):
        if inv_id not in now and status == "LOCKED":
            problems.append(f"{inv_id} was LOCKED at HEAD and its record was deleted. The CLI never deletes records.")
    return problems
