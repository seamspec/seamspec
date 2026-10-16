"""SeamSpec for Cursor, VS Code (Copilot) and Antigravity (SPEC §16.2–§16.4, ADR-20261013-e8f3).

Everything is a project file, written by `seamspec init --hosts …`, merged into what is already
there and never overwriting a value someone else set:

- **Rules:** the SeamSpec block in `AGENTS.md`, which all three read (worded for them: their command
  names, no reviewer).
- **Tools:** SeamSpec's MCP server in the host's project MCP config.
- **Hooks:** session start (the rules in force, new BRAINDUMP notes) and stop (the locked rules run;
  a failure sends the agent back to fix it or ask), through `seamspec hook <host> <event>`.
- **Commands:** `/seamspec-<name>`, rendered from the same templates as the Claude Code skills.

Edit-time context and ledger protection need each host's tool names, which its documentation doesn't
list; the commit gate and CI protect the ledger on every host.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import commands
from ..core.store import atomic_write
from . import directive

HOSTS = commands.OTHER_HOSTS
NAMES = {"cursor": "Cursor", "vscode": "VS Code (Copilot)", "antigravity": "Antigravity"}
MARKERS = {"cursor": ".cursor", "vscode": ".vscode", "antigravity": ".agents"}  # a host's folder: it's in use
MCP_SERVER = {"command": "seamspec", "args": ["mcp"]}
STOP_TIMEOUT = 300  # seconds; the Stop check finishes well inside it (§16.1)


@dataclass
class Change:
    path: str
    status: str  # created | updated | unchanged | kept (yours) | skipped (…)


def detect(root: Path) -> list[str]:
    """Hosts whose project folder exists here (or `.agent`, Antigravity's older name)."""
    found = [h for h in HOSTS if (root / MARKERS[h]).is_dir()]
    if "antigravity" not in found and (root / ".agent").is_dir():
        found.append("antigravity")
    return found


def _hook(host: str, event: str) -> str:
    return f"seamspec hook {host} {event}"


def mcp_entry(host: str, root: Path | None = None) -> tuple[str, list[str], dict[str, Any]]:
    """(file, path of keys to the server, the server's config).

    Antigravity starts MCP servers outside the project (in `/`) and fails on the server's question
    "which folders are open?" (`roots/list`), so every tool call ended in "unexpected end of JSON
    input" (hands-on test, 2026-10-14). Its config gets the project's absolute path instead: it has
    no `${workspaceFolder}`, and a rerun of `init` in another clone rewrites it (ADR-20261014-6c2d)."""
    if host == "vscode":
        server = {"type": "stdio", **MCP_SERVER, "env": {"SEAMSPEC_ROOT": "${workspaceFolder}"}}
        return ".vscode/mcp.json", ["servers", "seamspec"], server
    if host == "cursor":
        return ".cursor/mcp.json", ["mcpServers", "seamspec"], dict(MCP_SERVER)
    server = dict(MCP_SERVER)
    if root is not None:
        server["env"] = {"SEAMSPEC_ROOT": str(root.resolve())}
    return ".agents/mcp_config.json", ["mcpServers", "seamspec"], server


def hook_entries(host: str) -> tuple[str, dict[str, Any]]:
    """(file, the structure SeamSpec adds to it)."""
    if host == "cursor":
        return ".cursor/hooks.json", {"version": 1, "hooks": {
            "sessionStart": [{"command": _hook(host, "session-start")}],
            "stop": [{"command": _hook(host, "stop"), "timeout": STOP_TIMEOUT, "loop_limit": 3}],
        }}  # fmt: skip
    if host == "vscode":
        return ".github/hooks/seamspec.json", {"hooks": {
            "SessionStart": [{"type": "command", "command": _hook(host, "session-start"), "timeout": 30}],
            "Stop": [{"type": "command", "command": _hook(host, "stop"), "timeout": STOP_TIMEOUT}],
        }}  # fmt: skip
    return ".agents/hooks.json", {"seamspec": {
        "SessionStart": [{"type": "command", "command": _hook(host, "session-start"), "timeout": 30}],
        "Stop": [{"type": "command", "command": _hook(host, "stop"), "timeout": STOP_TIMEOUT}],
    }}  # fmt: skip


def _read_json(path: Path) -> dict[str, Any] | None:
    """The file's JSON object, {} when it doesn't exist, None when it can't be read safely."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(root: Path, rel: str, before: dict[str, Any], after: dict[str, Any], existed: bool) -> Change:
    if after == before:
        return Change(rel, "unchanged")
    atomic_write(root / rel, json.dumps(after, indent=2) + "\n")
    return Change(rel, "updated" if existed else "created")


def install_mcp(root: Path, host: str) -> Change:
    rel, keys, server = mcp_entry(host, root)
    data = _read_json(root / rel)
    if data is None:
        return Change(rel, "skipped (not a JSON object: add SeamSpec's server by hand)")
    before = json.loads(json.dumps(data))
    servers = data.setdefault(keys[0], {})
    if not isinstance(servers, dict):
        return Change(rel, f"skipped ({keys[0]} is not an object)")
    present = servers.get(keys[1])
    if present is None:
        servers[keys[1]] = server
    elif present != server:
        if not _ours(present):
            return Change(rel, "kept (yours)")
        # SeamSpec's own entry: bring its project folder up to date, keep anything else in it.
        if "env" in server:
            env = present.setdefault("env", {})
            if not isinstance(env, dict):
                return Change(rel, "kept (yours)")
            env.update(server["env"])
    return _write_json(root, rel, before, data, (root / rel).is_file())


def _ours(entry: Any) -> bool:
    """An entry that starts SeamSpec's server the way `init` writes it."""
    return (
        isinstance(entry, dict)
        and entry.get("command") == MCP_SERVER["command"]
        and entry.get("args") == MCP_SERVER["args"]
    )


def install_hooks(root: Path, host: str) -> Change:
    """Add SeamSpec's hook entries. An entry already running `seamspec hook <host> <event>` is left as
    it is, so a hand-tuned timeout survives a rerun; anyone else's hooks are never touched."""
    rel, ours = hook_entries(host)
    data = _read_json(root / rel)
    if data is None:
        return Change(rel, "skipped (not a JSON object: add SeamSpec's hooks by hand)")
    before = json.loads(json.dumps(data))
    if host == "antigravity":
        group = data.setdefault("seamspec", {})
        target, wanted = group, ours["seamspec"]
    else:
        if host == "cursor":
            data.setdefault("version", 1)
        target, wanted = data.setdefault("hooks", {}), ours["hooks"]
    if not isinstance(target, dict):
        return Change(rel, "skipped (unexpected structure: add SeamSpec's hooks by hand)")
    for event, entries in wanted.items():
        present = target.setdefault(event, [])
        if not isinstance(present, list):
            return Change(rel, f"skipped ({event} is not a list)")
        for entry in entries:
            if not any(isinstance(e, dict) and e.get("command") == entry["command"] for e in present):
                present.append(entry)
    return _write_json(root, rel, before, data, (root / rel).is_file())


def install_commands(root: Path, host: str) -> list[Change]:
    """Generated files, owned by SeamSpec (`seamspec-` prefix): rewritten to match this version."""
    out = []
    for name in commands.commands_for(host):
        rel = commands.HOST_FILES[host].format(name=name)
        text = commands.render(name, host)
        path = root / rel
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        if old == text:
            out.append(Change(rel, "unchanged"))
            continue
        atomic_write(path, text)
        out.append(Change(rel, "created" if old is None else "updated"))
    return out


def install_agents(root: Path, host: str) -> list[Change]:
    """SeamSpec's reviewer as the host's own read-only agent, where one can be made (ADR-20261015-4f7b)."""
    if host not in commands.AGENT_FILES:
        return []
    out = []
    for name in commands.V01_AGENTS:
        rel = commands.AGENT_FILES[host].format(name=name)
        text = commands.render_agent(name, host)
        path = root / rel
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        if old == text:
            out.append(Change(rel, "unchanged"))
            continue
        atomic_write(path, text)
        out.append(Change(rel, "created" if old is None else "updated"))
    return out


def install(root: Path, host: str) -> list[Change]:
    """Set SeamSpec up for one host. Safe to rerun."""
    if host not in HOSTS:
        raise ValueError(f"unknown host {host!r}; choose from {', '.join(HOSTS)}")
    status, kept = directive.install_keeping(root, directive.AGENTS_FILE)
    changes = [
        Change(directive.AGENTS_FILE, status + (f", kept {len(kept)} line(s) of yours above it" if kept else ""))
    ]
    changes += [install_mcp(root, host), install_hooks(root, host)]
    changes += install_commands(root, host)
    changes += install_agents(root, host)
    return changes
