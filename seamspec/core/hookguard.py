"""Hook guard for approvals in chat (ADR-20261006-c300, guard 1).

Claude Code lets an `Elicitation` hook answer an MCP dialog without showing it, and an
`ElicitationResult` hook rewrite the human's answer. Before each approval dialog, and again before
acting on the answer, SeamSpec looks in every place it can see for such a hook that could match
its server, and refuses chat approvals if it finds one (the human then uses `seamspec review`).

Places read: user, project and local settings (in the project folder and every folder above it),
managed settings, every enabled plugin (`hooks/hooks.json`, `plugin.json`, its skills and agents),
skill and agent files (their frontmatter can carry hooks), and the arguments Claude Code was started
with (`--settings`, `--plugin-dir`). Not visible: settings pushed from a server, and anything set up
in a place not listed. A file that can't be read counts as a problem: SeamSpec can't vouch for it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

SERVER = "plugin:seamspec:seamspec"  # the MCP server name hooks see for the plugin's server (verified)
EVENTS = ("Elicitation", "ElicitationResult")
_EXACT = re.compile(r"^[A-Za-z0-9_\-\s,|]*$")  # Claude Code: these characters mean exact names, else a regex
MANAGED_DIRS = (Path("/Library/Application Support/ClaudeCode"), Path("/etc/claude-code"))
MAX_PARENTS = 8


def matcher_matches(matcher: object, value: str = SERVER) -> bool:
    """Claude Code's matcher rules: missing, empty or `*` match everything; letters, digits, `_`,
    `-`, spaces, `,` and `|` give a list of exact names; anything else is an unanchored regex.
    Anything SeamSpec can't evaluate counts as a match."""
    if matcher is None:
        return True
    if not isinstance(matcher, str):
        return True
    m = matcher.strip()
    if m in ("", "*"):
        return True
    if _EXACT.match(m):
        return value in {part.strip() for part in re.split(r"[|,]", m)}
    try:
        return re.search(m, value) is not None
    except re.error:
        return True


def _hooks_in(doc: object) -> Iterator[tuple[str, object]]:
    """(event, matcher) for each Elicitation / ElicitationResult hook group in a settings-shaped document."""
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if not isinstance(hooks, dict):
        return
    for event in EVENTS:
        groups = hooks.get(event)
        if groups is None:
            continue
        if not isinstance(groups, list):
            yield event, None
            continue
        for group in groups:
            yield event, group.get("matcher") if isinstance(group, dict) else None


def _json_problems(path: Path, doc: object) -> list[str]:
    return [
        f"{path}: an {event} hook (matcher {matcher!r}) could answer or change SeamSpec's dialogs"
        for event, matcher in _hooks_in(doc)
        if matcher_matches(matcher)
    ]


def check_json_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return [f"{path}: can't be read, so SeamSpec can't check it for dialog hooks"]
    return _json_problems(path, doc)


def check_markdown_file(path: Path) -> list[str]:
    """Skill and agent files carry hooks in their frontmatter. Any mention of an Elicitation hook counts."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"{path}: can't be read, so SeamSpec can't check it for dialog hooks"]
    if not text.startswith("---"):
        return []
    front = text[3:].split("\n---", 1)[0]
    if "Elicitation" in front:
        return [f"{path}: its frontmatter mentions an Elicitation hook, which could answer SeamSpec's dialogs"]
    return []


def check_file(path: Path) -> list[str]:
    """One changed file (the ConfigChange hook): settings JSON or a skill / agent Markdown file."""
    if path.suffix == ".md":
        return check_markdown_file(path) if path.is_file() else []
    if path.is_dir():
        return _check_frontmatter_dirs([path])
    return check_json_file(path)


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _ancestors(paths: Iterable[Path]) -> list[Path]:
    seen: list[Path] = []
    for p in paths:
        for d in (p, *p.parents):
            if d not in seen:
                seen.append(d)
    return seen


def _settings_files(project_dirs: Iterable[Path]) -> list[Path]:
    cfg = config_dir()
    files = [cfg / "settings.json", cfg / "settings.local.json"]
    for d in _ancestors(project_dirs):
        files += [d / ".claude" / "settings.json", d / ".claude" / "settings.local.json"]
    for managed in MANAGED_DIRS:
        files.append(managed / "managed-settings.json")
        drop_in = managed / "managed-settings.d"
        if drop_in.is_dir():
            files += sorted(drop_in.glob("*.json"))
    return list(dict.fromkeys(files))


def _check_frontmatter_dirs(dirs: Iterable[Path]) -> list[str]:
    problems: list[str] = []
    for d in dirs:
        if d.is_dir():
            for md in sorted(d.rglob("*.md")):
                problems += check_markdown_file(md)
    return problems


def _enabled_plugins(settings: Iterable[Path]) -> set[str]:
    enabled: set[str] = set()
    for path in settings:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue  # reported by check_json_file
        plugins = doc.get("enabledPlugins") if isinstance(doc, dict) else None
        if isinstance(plugins, dict):
            enabled |= {name for name, on in plugins.items() if on}
    return enabled


def _read_json(path: Path, problems: list[str]) -> object:
    """A missing file is None; one that exists but can't be read is a problem (fail closed, Copilot #43)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        problems.append(f"{path}: can't be read, so SeamSpec can't check it for dialog hooks")
        return None


def _plugin_dirs(name: str, problems: list[str]) -> list[Path]:
    """Where an enabled plugin `name@marketplace` lives: its installed copy and, for a marketplace
    read from a folder, that folder's copy (which is what Claude Code loads)."""
    plugins = config_dir() / "plugins"
    dirs: list[Path] = []
    installed = _read_json(plugins / "installed_plugins.json", problems)
    entries = installed.get("plugins", {}).get(name, []) if isinstance(installed, dict) else []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
            dirs.append(Path(entry["installPath"]))
    plugin, _, market = name.partition("@")
    markets = _read_json(plugins / "known_marketplaces.json", problems)
    location = markets.get(market, {}).get("installLocation") if isinstance(markets, dict) else None
    if isinstance(location, str):
        manifest = _read_json(Path(location) / ".claude-plugin" / "marketplace.json", problems)
        for item in manifest.get("plugins", []) if isinstance(manifest, dict) else []:
            if isinstance(item, dict) and item.get("name") == plugin and isinstance(item.get("source"), str):
                dirs.append((Path(location) / item["source"]).resolve())
    return list(dict.fromkeys(dirs))


def check_plugin_dir(d: Path) -> list[str]:
    problems = check_json_file(d / "hooks" / "hooks.json")
    manifest_path = d / ".claude-plugin" / "plugin.json"
    manifest = _read_json(manifest_path, problems)
    hooks = manifest.get("hooks") if isinstance(manifest, dict) else None
    if isinstance(hooks, dict):
        problems += _json_problems(manifest_path, {"hooks": hooks.get("hooks", hooks)})
    elif isinstance(hooks, str | list):
        for rel in [hooks] if isinstance(hooks, str) else hooks:
            if isinstance(rel, str):
                problems += check_json_file(d / rel)
    return problems + _check_frontmatter_dirs([d / "skills", d / "agents"])


def _launch_args() -> list[str] | None:
    """The command lines of the processes that started this one (Claude Code is among them). None when
    they can't be read (Windows, or `ps` failing): the caller then can't vouch for them."""
    if sys.platform == "win32":
        return None
    out: list[str] = []
    pid = os.getppid()
    for _ in range(MAX_PARENTS):
        if pid <= 1:
            break
        try:
            ps = subprocess.run(["ps", "-ww", "-o", "ppid=,args=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=5)  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return out or None
        parts = ps.stdout.strip().split(None, 1)
        if ps.returncode != 0 or len(parts) < 2:
            if not out:
                return None  # not even our own parent: nothing was checked
            break  # an ancestor exited meanwhile: the ones read are checked
        out.append(parts[1])
        pid = int(parts[0]) if parts[0].isdigit() else 0
    return out


def _check_launch_args(args: list[str]) -> list[str]:
    problems: list[str] = []
    for line in args:
        if "Elicitation" in line:
            problems.append("Claude Code was started with settings that mention an Elicitation hook")
        for flag in ("--plugin-dir", "--settings"):
            for match in re.finditer(rf"{flag}[ =](\S+)", line):
                value = Path(match.group(1).strip("'\""))
                if flag == "--plugin-dir" and value.is_dir():
                    problems += check_plugin_dir(value)
                elif flag == "--settings" and value.is_file():
                    problems += check_json_file(value)
    return problems


UNCHECKED_LAUNCH = "the arguments Claude Code was started with can't be checked here (e.g. on Windows)"
USE_DEFAULT = object()


def scan(project_dirs: Iterable[Path], launch_args: list[str] | None | object = USE_DEFAULT) -> list[str]:
    """Every hook SeamSpec can see that could answer or change its dialogs. Empty means none found.
    `launch_args`: the command lines to check (default: read them); None means they couldn't be read."""
    project_dirs = list(project_dirs)
    settings = _settings_files(project_dirs)
    problems: list[str] = []
    for path in settings:
        problems += check_json_file(path)
    for name in sorted(_enabled_plugins(settings)):
        dirs = _plugin_dirs(name, problems)
        if not dirs:
            problems.append(f"plugin {name} is enabled but SeamSpec can't find where it's installed")
        for d in dirs:
            problems += check_plugin_dir(d)
    cfg = config_dir()
    folders = [cfg / "skills", cfg / "agents"]
    for d in _ancestors(project_dirs):
        folders += [d / ".claude" / "skills", d / ".claude" / "agents"]
    problems += _check_frontmatter_dirs(dict.fromkeys(folders))
    args = _launch_args() if launch_args is USE_DEFAULT else launch_args
    problems += [UNCHECKED_LAUNCH] if args is None else _check_launch_args(args)  # type: ignore[arg-type]
    return list(dict.fromkeys(problems))
