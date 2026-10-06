"""Install and enable the SeamSpec Claude Code plugin for one repository (SPEC §16.1).

Runs Claude Code's own CLI, never edits its settings files directly:

    claude plugin marketplace add <checkout> --scope local
    claude plugin install seamspec@seamspec --scope local

`local` scope writes only `<repo>/.claude/settings.local.json` (this user, this repository), so
nothing changes for other projects or teammates. The marketplace is the SeamSpec checkout the
CLI runs from (`.claude-plugin/marketplace.json`); a published marketplace, and with it
`project` scope for teams, arrives with the release (ADR-20261005-3adc).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .scaffold import merge_gitignore

PLUGIN_ID = "seamspec@seamspec"
SCOPE = "local"
SETTINGS_LOCAL = ".claude/settings.local.json"
TIMEOUT_SECONDS = 120


@dataclass
class PluginResult:
    status: str  # installed | unchanged | skipped | failed
    message: str = ""
    gitignore: str | None = None  # what happened to .gitignore (created | updated | unchanged)


def marketplace_source() -> Path | None:
    """The checkout this CLI runs from, if it has the marketplace file (editable installs)."""
    checkout = Path(__file__).resolve().parents[2]
    return checkout if (checkout / ".claude-plugin" / "marketplace.json").is_file() else None


def _claude(root: Path, *args: str) -> tuple[bool, str]:
    """Run `claude plugin ...`; (ok, message from its --json result line or its output)."""
    try:
        out = subprocess.run(
            ["claude", "plugin", *args, "--json"],
            cwd=root, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    text = (out.stdout or "").strip()
    try:
        result = json.loads(text.splitlines()[-1]) if text else {}
    except json.JSONDecodeError:
        result = {}
    ok = out.returncode == 0 and result.get("outcome", "ok") == "ok"
    message = str(result.get("message") or (out.stderr or text).strip())
    return ok, message


def enabled_here(root: Path) -> bool:
    """Is the plugin already enabled for this repository (any scope)?"""
    try:
        out = subprocess.run(
            ["claude", "plugin", "list", "--json"], cwd=root, capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )
        plugins = json.loads(out.stdout) if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    here = str(root.resolve())
    for p in plugins if isinstance(plugins, list) else []:
        if not isinstance(p, dict) or p.get("id") != PLUGIN_ID or not p.get("enabled"):
            continue
        if p.get("scope") == "user" or str(Path(p.get("projectPath") or "/nonexistent").resolve()) == here:
            return True
    return False


def commands(source: Path) -> list[tuple[str, ...]]:
    """The `claude plugin` invocations `enable()` runs, for showing them before asking."""
    return [("marketplace", "add", str(source), "--scope", SCOPE), ("install", PLUGIN_ID, "--scope", SCOPE)]


def _ignore_local_settings(root: Path) -> str | None:
    """`.claude/settings.local.json` holds this machine's checkout path: never commit it. Only when
    the file exists, so a manual install, or an install that failed halfway, is covered too."""
    if not (root / SETTINGS_LOCAL).exists():
        return None
    return merge_gitignore(root, (SETTINGS_LOCAL,), "SeamSpec: Claude Code plugin enabled on this machine only")


def precheck(root: Path) -> PluginResult | None:
    """Why there is nothing to install (skipped / unchanged), or None when `enable()` can run."""
    root = root.resolve()
    if shutil.which("claude") is None:
        return PluginResult("skipped", "Claude Code CLI (`claude`) not found on PATH")
    source = marketplace_source()
    if source is None:
        return PluginResult(
            "skipped",
            "the plugin ships with the release; until then install SeamSpec from a checkout "
            "(`uv tool install --force --editable <path-to-seamspec-repo>`)",
        )
    if enabled_here(root):
        message = f"{PLUGIN_ID} is already enabled for this repository"
        return PluginResult("unchanged", message, _ignore_local_settings(root))
    return None


def enable(root: Path) -> PluginResult:
    """Run the `commands()` (after `precheck()` returned None and the human said yes)."""
    root = root.resolve()
    source = marketplace_source()
    if source is None:
        return PluginResult("skipped", "no SeamSpec checkout to install the plugin from")
    for args in commands(source):
        ok, message = _claude(root, *args)
        if not ok:
            failed = f"`claude plugin {' '.join(args)}` failed: {message}"
            return PluginResult("failed", failed, _ignore_local_settings(root))  # `add` may have written it
    message = f"{PLUGIN_ID} enabled for this repository only, in {SETTINGS_LOCAL}"
    return PluginResult("installed", message, _ignore_local_settings(root))


def install(root: Path) -> PluginResult:
    """`precheck()` then `enable()`, for callers that already have the human's yes."""
    return precheck(root) or enable(root)
