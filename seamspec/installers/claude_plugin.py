"""Install and enable the SeamSpec Claude Code plugin for one repository (SPEC §16.1).

Runs Claude Code's own CLI, never edits its settings files directly:

    claude plugin marketplace add <source> --scope local|project
    claude plugin install seamspec@seamspec --scope local|project

The source (ADR-20261023-7d41): a released SeamSpec takes the plugin from this repository on
GitHub, pinned to the tag of the installed version, so the plugin and the CLI always match. A
checkout (editable install) uses itself, so plugin edits apply at the next session.

`local` scope writes only `<repo>/.claude/settings.local.json` (this user, this repository).
`project` scope writes the committed `<repo>/.claude/settings.json`, so every teammate's Claude
Code offers the plugin once they trust the folder; only a published source can go there, never a
path on this machine.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from .ci import REPOSITORY, released
from .scaffold import merge_gitignore

PLUGIN_ID = "seamspec@seamspec"
SCOPES = ("local", "project")
SETTINGS = {"local": ".claude/settings.local.json", "project": ".claude/settings.json"}
SETTINGS_LOCAL = SETTINGS["local"]
SOURCE_ENV = "SEAMSPEC_PLUGIN_MARKETPLACE"  # any source `claude plugin marketplace add` takes (release rehearsal)
_GITHUB_SHORT = re.compile(r"[\w.-]+/[\w.-]+(#\S+)?")  # owner/repo[#ref]
TIMEOUT_SECONDS = 120


@dataclass
class PluginResult:
    status: str  # installed | unchanged | skipped | failed
    message: str = ""
    gitignore: str | None = None  # what happened to .gitignore (created | updated | unchanged)


def checkout() -> Path | None:
    """The checkout this CLI runs from, if it has the marketplace file (editable installs)."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / ".claude-plugin" / "marketplace.json").is_file() else None


def release_source(version: str | None = None) -> str:
    """This repository on GitHub, pinned to the version's tag. HTTPS, so no GitHub SSH key is needed."""
    return f"{REPOSITORY}.git#v{__version__ if version is None else version}"


def marketplace_source() -> str | None:
    """Where Claude Code gets the plugin: $SEAMSPEC_PLUGIN_MARKETPLACE when set, else the checkout this
    CLI runs from, else (a released version) its tag on GitHub. None for an unreleased build installed
    without a checkout: there is no tag to pin to."""
    if os.environ.get(SOURCE_ENV, "").strip():
        return os.environ[SOURCE_ENV].strip()
    if (root := checkout()) is not None:
        return str(root)
    return release_source() if released() else None


def shareable(source: str) -> bool:
    """Can the source go into the committed settings file? A URL or `owner/repo` can; a path can't."""
    return source.startswith("https://") or (
        _GITHUB_SHORT.fullmatch(source) is not None and not Path(source.split("#")[0]).exists()
    )


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


def commands(source: str, scope: str = "local") -> list[tuple[str, ...]]:
    """The `claude plugin` invocations `enable()` runs, for showing them before asking."""
    return [("marketplace", "add", source, "--scope", scope), ("install", PLUGIN_ID, "--scope", scope)]


def _ignore_local_settings(root: Path) -> str | None:
    """`.claude/settings.local.json` holds this machine's checkout path: never commit it. Only when
    the file exists, so a manual install, or an install that failed halfway, is covered too."""
    if not (root / SETTINGS_LOCAL).exists():
        return None
    return merge_gitignore(root, (SETTINGS_LOCAL,), "SeamSpec: Claude Code plugin enabled on this machine only")


def precheck(root: Path, scope: str = "local") -> PluginResult | None:
    """Why there is nothing to install (skipped / unchanged), or None when `enable()` can run."""
    root = root.resolve()
    if shutil.which("claude") is None:
        return PluginResult("skipped", "Claude Code CLI (`claude`) not found on PATH")
    source = marketplace_source()
    if source is None:
        return PluginResult(
            "skipped",
            f"this SeamSpec ({__version__}) is an unreleased build, so there is no published plugin to match "
            "it; install SeamSpec from a checkout (`uv tool install --force --editable <path-to-seamspec-repo>`)",
        )
    if scope == "project" and not shareable(source):
        return PluginResult(
            "skipped",
            f"the plugin comes from a folder on this machine ({source}), which can't go into the committed "
            f"{SETTINGS['project']}; it can be turned on for you only (`--plugin-scope local`)",
        )
    if enabled_here(root):
        message = f"{PLUGIN_ID} is already enabled for this repository"
        return PluginResult("unchanged", message, _ignore_local_settings(root))
    return None


def enable(root: Path, scope: str = "local") -> PluginResult:
    """Run the `commands()` (after `precheck()` returned None and the human said yes)."""
    root = root.resolve()
    source = marketplace_source()
    if source is None:
        return PluginResult("skipped", "no published plugin or SeamSpec checkout to install it from")
    for args in commands(source, scope):
        ok, message = _claude(root, *args)
        if not ok:
            failed = f"`claude plugin {' '.join(args)}` failed: {message}"
            return PluginResult("failed", failed, _ignore_local_settings(root))  # `add` may have written it
    if scope == "project":
        message = f"{PLUGIN_ID} enabled for everyone in this repository, in {SETTINGS['project']} (commit it)"
    else:
        message = f"{PLUGIN_ID} enabled for this repository only, in {SETTINGS_LOCAL}"
    return PluginResult("installed", message, _ignore_local_settings(root))


def install(root: Path, scope: str = "local") -> PluginResult:
    """`precheck()` then `enable()`, for callers that already have the human's yes."""
    return precheck(root, scope) or enable(root, scope)
